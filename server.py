"""Local HTTP API for the UI: start a jiffusion run and stream its steps. Standard library only.

    uv run server.py            # http://127.0.0.1:8787
    POST /api/runs   {"prompt": "a duck", "size": 24, "steps": 150, "seed": 0, "candidates": 8, "patience": 30}
    GET  /api/runs/<id>?from=N  -> {"settings": ..., "steps": [records N..], "noise": "..."}

The TypeSafe key stays on this side; the browser never sees it.
"""

from contextlib import nullcontext
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import traceback
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from typesafe_sdk import TypeSafeClient

from jiffusion import run

RUNS = Path("runs")
LIMITS = dict(size=(4, 40), steps=(1, 500), candidates=(1, 32), patience=(1, 500), seed=(0, 2**31 - 1))
STATE = {}  # run id -> dict(output=Path, error=str|None, thread=Thread)
LOCK = threading.Lock()


def start_run(params):
    settings = {}
    for key, (low, high) in LIMITS.items():
        if key in params:
            settings[key] = min(high, max(low, int(params[key])))
    prompt = str(params.get("prompt", "")).strip()
    if not prompt:
        raise ValueError("prompt is required")
    selector = params.get("selector", "score")
    if selector not in ("score", "jev", "random"):
        raise ValueError("selector must be score, jev, or random")
    run_id = datetime.now(timezone.utc).strftime("ui-%Y%m%d-%H%M%S-%f")
    output = RUNS / run_id
    state = dict(output=output, error=None, done=False)

    def work():
        try:
            with TypeSafeClient(timeout=60) if selector != "random" else nullcontext(None) as client:
                run(client, prompt=prompt, output=output, selector=selector, **settings)
        except Exception as exc:  # surfaced to the UI; the run's manifest also records the failure
            key = os.environ.get("TYPESAFE_API_KEY", "")
            state["error"] = str(exc).replace(key, "[redacted]") if key else str(exc)
            traceback.print_exc()
        finally:
            state["done"] = True

    state["thread"] = threading.Thread(target=work, daemon=True)
    with LOCK:
        STATE[run_id] = state
    state["thread"].start()
    return run_id


def read_run(run_id, start):
    with LOCK:
        state = STATE.get(run_id)
    output = state["output"] if state else RUNS / run_id
    if not (output / "run.json").is_file():
        if state and state["error"]:
            return dict(id=run_id, error=state["error"], done=True, settings=None, steps=[], noise=None)
        return None
    settings = json.loads((output / "run.json").read_text(encoding="utf-8"))
    steps_path = output / "steps.jsonl"
    lines = steps_path.read_text(encoding="utf-8").splitlines() if steps_path.is_file() else []
    steps = [json.loads(line) for line in lines[start:]]
    noise = None
    frames = output / "frames.md"
    if frames.is_file():
        blocks = frames.read_text(encoding="utf-8").split("```text\n")
        if len(blocks) > 1:
            noise = blocks[1].split("```")[0].rstrip("\n")
    done = settings["status"] != "running" or bool(state and state["done"])
    return dict(id=run_id, settings=settings, steps=steps, total=len(lines), noise=noise, done=done,
                error=state["error"] if state else None)


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        parts = url.path.strip("/").split("/")
        if parts[:2] == ["api", "runs"] and len(parts) == 3:
            start = int(parse_qs(url.query).get("from", ["0"])[0])
            payload = read_run(parts[2], start)
            return self.send_json(payload) if payload else self.send_json({"error": "unknown run"}, 404)
        if parts == ["api", "health"]:
            return self.send_json({"ok": True, "key": bool(os.environ.get("TYPESAFE_API_KEY", "").strip())})
        self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if urlparse(self.path).path.rstrip("/") != "/api/runs":
            return self.send_json({"error": "not found"}, 404)
        length = int(self.headers.get("Content-Length", "0"))
        try:
            params = json.loads(self.rfile.read(length) or b"{}")
            run_id = start_run(params)
        except (ValueError, TypeError) as exc:
            return self.send_json({"error": str(exc)}, 400)
        self.send_json({"id": run_id}, 201)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main():
    load_dotenv(Path(__file__).with_name(".env"))
    port = int(os.environ.get("JIFFUSION_PORT", "8787"))
    RUNS.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"jiffusion API on http://127.0.0.1:{port}  (TYPESAFE_API_KEY "
          f"{'set' if os.environ.get('TYPESAFE_API_KEY', '').strip() else 'MISSING'})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
