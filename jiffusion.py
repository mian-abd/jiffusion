"""Five-level brightness edits, one Jev choice per step."""

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

from prompts import ASCII_LEGEND, CHOICE_INSTRUCTIONS, DEFAULT_PROMPT, EXPLICIT_CIRCLE_PROMPT, PALETTE

MODEL = "jev-1.13.0"


def schedule(steps, patch_size=None):
    """One coarse initialization, then quickly shrink edits from 4x4 to 1x1."""
    if patch_size is not None:
        return [0] + [patch_size] * (steps - 1)
    return [0] + [
        4 if step < steps * 0.1 else 2 if step < steps * 0.4 else 1
        for step in range(1, steps)
    ]


def resolution_schedule(size, steps, progressive=False):
    """Spend 30% of steps at 5x5, 30% at 10x10, then use the final size."""
    return [
        min(5, size) if progressive and step < int(steps * 0.3)
        else min(10, size) if progressive and step < int(steps * 0.6)
        else size
        for step in range(steps)
    ]


def brightness_schedule(steps):
    """Allow jumps of four, two, then one palette level in the same 10/30/60% phases."""
    return schedule(steps)


def resize_grid(grid, size):
    """Nearest-neighbor enlargement preserves the selected coarse pattern."""
    old_size = len(grid)
    return [[grid[y * old_size // size][x * old_size // size]
             for x in range(size)] for y in range(size)]


def random_grid(size, rng):
    """Enlarge a random 5x5 grid using all five brightness levels."""
    coarse_size = min(5, size)
    coarse = [[rng.randrange(len(PALETTE)) for _ in range(coarse_size)] for _ in range(coarse_size)]
    return resize_grid(coarse, size)


def mutate(grid, patch_size, rng, max_brightness_change=4):
    """Shift a patch's brightness, clipping at endpoints; its anchor must change."""
    if not 1 <= max_brightness_change < len(PALETTE):
        raise ValueError("Brightness changes must be between one and four levels")
    size = len(grid)
    width = min(patch_size, size)
    y, x = rng.randrange(size - width + 1), rng.randrange(size - width + 1)
    old = grid[y][x]
    value = rng.choice([level for level in range(len(PALETTE))
                        if 0 < abs(level - old) <= max_brightness_change])
    delta = value - old
    result = [row.copy() for row in grid]
    for row in range(y, y + width):
        result[row][x:x + width] = [min(4, max(0, pixel + delta))
                                    for pixel in grid[row][x:x + width]]
    return result


def render(grid):
    return "\n".join("".join(PALETTE[value] for value in row) for row in grid)


def jev_pick(client, prompt, candidates, model=MODEL, *, instructions=CHOICE_INSTRUCTIONS):
    return jev_pick_ascii(client, prompt, [render(grid) for grid in candidates],
                          model=model, instructions=instructions)


def jev_pick_ascii(client, prompt, candidates, model=MODEL, *, instructions=CHOICE_INSTRUCTIONS):
    """Shared production/optimization request; labels and references never enter state."""
    grids = {f"c{i:03}": grid for i, grid in enumerate(candidates)}
    response = client.system_one(
        model=model,
        state={
            "prompt": prompt,
            "legend": ASCII_LEGEND,
            "candidates": grids,
        },
        questions={"best": Choice(
            instructions=instructions,
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


def run(client, *, prompt=DEFAULT_PROMPT, size=20, steps=750, candidates=16, seed=0,
        model=MODEL, output, selector="jev", progressive=False, patch_size=None,
        instructions=CHOICE_INSTRUCTIONS, verbose=True):
    if size < 1 or steps < 1 or not 1 <= candidates <= 255:
        raise ValueError("Size and steps must be positive; candidates must be between 1 and 255")
    if not prompt.strip() or selector not in {"jev", "random"}:
        raise ValueError("Provide a nonempty prompt and a jev or random selector")
    if patch_size is not None and patch_size < 1:
        raise ValueError("Patch size must be positive")
    if selector == "jev" and client is None:
        raise ValueError("The jev selector requires a TypeSafe client")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    settings = dict(prompt=prompt, size=size, steps=steps, candidates=candidates,
                    seed=seed, model=model if selector == "jev" else None, selector=selector,
                    generator="grayscale-delta-patches-v3", initial_grid_size=min(5, size), levels=list(range(5)),
                    allow_unchanged=False,
                    encoding="ascii-five-level-v1", legend=ASCII_LEGEND,
                    question=instructions, progressive=progressive,
                    resolutions=resolution_schedule(size, steps, progressive),
                    schedule=schedule(steps, 1 if progressive and patch_size is None else patch_size),
                    brightness_schedule=brightness_schedule(steps),
                    status="running", completed_steps=0)
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
                grid_size = settings["resolutions"][step - 1]
                if current is not None and len(current) != grid_size:
                    current = resize_grid(current, grid_size)
                options = [
                    random_grid(grid_size, rng) if current is None
                    else mutate(current, patch_size, rng, settings["brightness_schedule"][step - 1])
                    for _ in range(candidates)
                ]
                rng.shuffle(options)
                request_started = time.perf_counter()
                selected, detail = (
                    jev_pick(client, prompt, options, model, instructions=instructions) if selector == "jev"
                    else (chooser.randrange(len(options)), {})
                )
                unchanged = options[selected] == current
                changed_pixels = None if current is None else sum(
                    before != after for old_row, new_row in zip(current, options[selected])
                    for before, after in zip(old_row, new_row)
                )
                max_changed_brightness = None if current is None else max(
                    abs(before - after) for old_row, new_row in zip(current, options[selected])
                    for before, after in zip(old_row, new_row)
                )
                current = options[selected]
                elapsed = time.perf_counter() - request_started
                record = dict(step=step, grid_size=grid_size, patch_size=patch_size, changed_pixels=changed_pixels,
                              brightness_limit=settings["brightness_schedule"][step - 1],
                              max_changed_brightness=max_changed_brightness,
                              selected_index=selected, unchanged=unchanged, seconds=elapsed,
                              candidates=[render(grid) for grid in options], **detail)
                log.write(json.dumps(record, ensure_ascii=False) + "\n")
                log.flush()
                frames.write(f"## Step {step} ({grid_size}×{grid_size})\n\n```text\n{render(current)}\n```\n\n")
                frames.flush()
                settings["completed_steps"] = step
                manifest.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
                if verbose:
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
    parser.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT)
    parser.add_argument("--explicit-circle", action="store_true",
                        help="use EXPLICIT_CIRCLE_PROMPT from prompts.py")
    parser.add_argument("--size", type=int, default=20)
    parser.add_argument("--steps", type=int, default=750)
    parser.add_argument("--candidates", type=int, default=16, help="new grids per step (default: 16)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--selector", choices=["jev", "random"], default="jev")
    parser.add_argument("--progressive", action="store_true",
                        help="evolve at 5x5, then 10x10, then --size; defaults to one-pixel edits")
    parser.add_argument("--patch-size", type=int,
                        help="use a fixed patch width instead of shrinking edits")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.explicit_circle:
        args.prompt = EXPLICIT_CIRCLE_PROMPT
    del args.explicit_circle
    if args.size < 1 or args.steps < 1 or not 1 <= args.candidates <= 255 or not args.prompt.strip():
        parser.error("Provide a nonempty prompt, positive size/steps, and 1–255 candidates")
    if args.patch_size is not None and args.patch_size < 1:
        parser.error("--patch-size must be positive")
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
