"""Vercel serverless entrypoint: runs a jiffusion generation synchronously and
returns the full run record. The TypeSafe key stays in Vercel env vars.

    POST /api  {"prompt": "a circle", "size": 20, "steps": 100, "seed": 0,
                "candidates": 8, "patience": 30}
    GET  /api -> {"ok": true, "key": true}
"""

from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typesafe_sdk import TypeSafeClient  # noqa: E402

from jiffusion import run  # noqa: E402

LIMITS = dict(size=(4, 40), steps=(1, 500), candidates=(1, 32), patience=(1, 500), seed=(0, 2**31 - 1))


def run_sync(params):
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

    with tempfile.TemporaryDirectory(prefix="jiffusion-") as tmp:
        output = Path(tmp) / "run"
        error = None
        try:
            with TypeSafeClient(timeout=60) if selector != "random" else _nullctx() as client:
                run(client, prompt=prompt, output=output, selector=selector, **settings)
        except Exception as exc:
            key = os.environ.get("TYPESAFE_API_KEY", "")
            error = str(exc).replace(key, "[redacted]") if key else str(exc)
            traceback.print_exc()

        manifest = output / "run.json"
        manifest_data = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else None
        steps_path = output / "steps.jsonl"
        steps = [json.loads(l) for l in steps_path.read_text(encoding="utf-8").splitlines()] if steps_path.is_file() else []
        noise = None
        frames = output / "frames.md"
        if frames.is_file():
            blocks = frames.read_text(encoding="utf-8").split("```text\n")
            if len(blocks) > 1:
                noise = blocks[1].split("```")[0].rstrip("\n")

    return dict(id="vercel", settings=manifest_data, steps=steps, total=len(steps), noise=noise,
                done=True, error=error)


class _nullctx:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


class handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send_json({"ok": True, "key": bool(os.environ.get("TYPESAFE_API_KEY", "").strip())})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        try:
            params = json.loads(self.rfile.read(length) or b"{}")
            payload = run_sync(params)
        except (ValueError, TypeError) as exc:
            return self.send_json({"error": str(exc)}, 400)
        self.send_json(payload)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))
