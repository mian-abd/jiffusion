"""Random black-and-white patch edits, one Jev choice per step."""

import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import sys
import time

from dotenv import load_dotenv
from typesafe_sdk import Choice, TypeSafeClient, TypeSafeError

PALETTE = " ░▒▓█"
MODEL = "jev-1.13.0"


def schedule(steps):
    """One coarse initialization, then quickly shrink edits from 4x4 to 1x1."""
    return [0] + [
        4 if step < steps * 0.1 else 2 if step < steps * 0.4 else 1
        for step in range(1, steps)
    ]


def random_grid(size, rng):
    """Enlarge a random 5x5 binary grid with nearest-neighbor sampling."""
    coarse_size = min(5, size)
    coarse = [[rng.choice((0, 4)) for _ in range(coarse_size)] for _ in range(coarse_size)]
    return [[coarse[y * coarse_size // size][x * coarse_size // size]
             for x in range(size)] for y in range(size)]


def mutate(grid, patch_size, rng):
    """Paint one square uniformly; changing its anchor guarantees a real edit."""
    size = len(grid)
    width = min(patch_size, size)
    y, x = rng.randrange(size - width + 1), rng.randrange(size - width + 1)
    value = 4 - grid[y][x]
    result = [row.copy() for row in grid]
    for row in range(y, y + width):
        result[row][x:x + width] = [value] * width
    return result


def render(grid):
    return "\n".join("".join(PALETTE[value] for value in row) for row in grid)


def jev_pick(client, prompt, candidates, model=MODEL):
    grids = {f"c{i:03}": render(grid) for i, grid in enumerate(candidates)}
    response = client.system_one(
        model=model,
        state={
            "prompt": prompt,
            "legend": "Each character is one square pixel: space=white and █=black. "
                      "Newlines separate rows, top to bottom. "
                      "Read each grid as a spatial image; preserve its whitespace.",
            "candidates": grids,
        },
        questions={"best": Choice(
            instructions="Which grid in `candidates` best depicts `prompt`? "
                         "Choose the closest visual resemblance, even if all candidates are poor.",
            criteria={key: None for key in grids},
        )},
    )
    answer = response.choices["best"]
    if answer.choice not in grids:
        raise ValueError("Jev returned an unknown candidate ID")
    return list(grids).index(answer.choice), {
        "model": response.model,
        "usage": response.usage.model_dump(),
        "answer": answer.model_dump(),
    }


def save_svg(grid, path):
    """A square-pixel preview, independent of terminal font proportions."""
    size = len(grid)
    pixels = [
        f'<rect x="{x}" y="{y}" width="1" height="1" fill="rgb({v},{v},{v})"/>'
        for y, row in enumerate(grid)
        for x, value in enumerate(row)
        for v in [round(255 * (4 - value) / 4)]
    ]
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" '
        f'viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
        + "".join(pixels) + "</svg>\n", encoding="utf-8",
    )


def run(client, *, prompt="a circle", size=20, steps=500, candidates=16, seed=0,
        model=MODEL, output, selector="jev"):
    if size < 1 or steps < 1 or not 1 <= candidates <= 255:
        raise ValueError("Size and steps must be positive; candidates must be between 1 and 255")
    if not prompt.strip() or selector not in {"jev", "random"}:
        raise ValueError("Provide a nonempty prompt and a jev or random selector")
    if selector == "jev" and client is None:
        raise ValueError("The jev selector requires a TypeSafe client")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    settings = dict(prompt=prompt, size=size, steps=steps, candidates=candidates,
                    seed=seed, model=model if selector == "jev" else None, selector=selector,
                    generator="binary-patches-v1", initial_grid_size=min(5, size), levels=[0, 4],
                    allow_unchanged=False,
                    schedule=schedule(steps), status="running", completed_steps=0)
    manifest = output / "run.json"
    manifest.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    rng, chooser = random.Random(seed), random.Random(seed)
    current = None
    started = time.perf_counter()
    try:
        with (output / "frames.md").open("w", encoding="utf-8") as frames, \
                (output / "steps.jsonl").open("w", encoding="utf-8") as log:
            frames.write(f"# {prompt}\n\n{size}×{size}, {steps} steps, seed {seed}, {selector}.\n\n")
            for step, patch_size in enumerate(settings["schedule"], 1):
                options = [
                    random_grid(size, rng) if current is None
                    else mutate(current, patch_size, rng)
                    for _ in range(candidates)
                ]
                rng.shuffle(options)
                request_started = time.perf_counter()
                selected, detail = (
                    jev_pick(client, prompt, options, model) if selector == "jev"
                    else (chooser.randrange(len(options)), {})
                )
                unchanged = options[selected] == current
                changed_pixels = None if current is None else sum(
                    before != after for old_row, new_row in zip(current, options[selected])
                    for before, after in zip(old_row, new_row)
                )
                current = options[selected]
                elapsed = time.perf_counter() - request_started
                record = dict(step=step, patch_size=patch_size, changed_pixels=changed_pixels,
                              selected_index=selected, unchanged=unchanged, seconds=elapsed,
                              candidates=[render(grid) for grid in options], **detail)
                log.write(json.dumps(record, ensure_ascii=False) + "\n")
                log.flush()
                frames.write(f"## Step {step}\n\n```text\n{render(current)}\n```\n\n")
                frames.flush()
                settings["completed_steps"] = step
                manifest.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
                print(f"{step:02}/{steps}: c{selected:03}, {elapsed:.2f}s", flush=True)
        settings["status"] = "complete"
    except BaseException as exc:
        settings["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        settings["error_type"] = type(exc).__name__
        raise
    finally:
        settings["seconds"] = time.perf_counter() - started
        manifest.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        if current is not None:
            (output / "final.txt").write_text(render(current) + "\n", encoding="utf-8")
            save_svg(current, output / "final.svg")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", default="a circle")
    parser.add_argument("--size", type=int, default=20)
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--candidates", type=int, default=16, help="new grids per step (default: 16)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--selector", choices=["jev", "random"], default="jev")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.size < 1 or args.steps < 1 or not 1 <= args.candidates <= 255 or not args.prompt.strip():
        parser.error("Provide a nonempty prompt, positive size/steps, and 1–255 candidates")
    load_dotenv(Path(__file__).with_name(".env"))
    if args.selector == "jev" and not os.environ.get("TYPESAFE_API_KEY", "").strip():
        parser.error("Set TYPESAFE_API_KEY in .env or your environment")
    args.output = args.output or Path("runs") / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    print(f"Saving run to {args.output.resolve()}", flush=True)
    try:
        with TypeSafeClient(timeout=60) if args.selector == "jev" else nullcontext(None) as client:
            run(client, **vars(args))
    except (TypeSafeError, ValueError, OSError) as exc:
        message = str(exc)
        key = os.environ.get("TYPESAFE_API_KEY", "")
        if key:
            message = message.replace(key, "[redacted]")
        print(f"Stopped: {message}", file=sys.stderr)
        if "max_tokens_exceeded" in message:
            print("Reduce --candidates or --size to fit Jev's context limit.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped; completed frames are saved.", file=sys.stderr)
        return 130
    print(f"Done: {args.output.resolve() / 'frames.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
