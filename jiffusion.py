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
from typesafe_sdk import Choice, Score, TypeSafeClient, TypeSafeError

PALETTE = " ░▒▓█"
MODEL = "jev-1.13.0"
MIN_EXTENT = 4  # Jev distinguishes edits of about this footprint; smaller ones read as noise.
KEEP = "keep"
PRIMITIVES = ("ellipse", "ring", "rect", "line")
TRANSFORMS = ("stretch", "shift")
DENOISERS = ("smooth", "erode", "dilate", "fill", "threshold")
# Share of proposals per family: local denoise operators, whole-image transforms, then strokes.
DENOISE_RATE, TRANSFORM_RATE = 0.25, 0.25


def schedule(steps, size=20):
    """One initialization, then shrink the stroke extent linearly to MIN_EXTENT."""
    start = max(MIN_EXTENT, round(size * 0.6))
    return [0] + [
        max(MIN_EXTENT, round(start - (start - MIN_EXTENT) * step / max(1, steps - 1)))
        for step in range(1, steps)
    ]


def blank(size):
    return [[0] * size for _ in range(size)]


def footprint(kind, size, extent, rng):
    """Pixels covered by one random primitive whose bounding box is at most `extent` wide."""
    low = min(2, size)
    extent = max(low, min(extent, size))
    if kind == "line":
        y0, x0 = rng.randrange(size), rng.randrange(size)
        y1 = min(size - 1, max(0, y0 + rng.randint(-extent, extent)))
        x1 = min(size - 1, max(0, x0 + rng.randint(-extent, extent)))
        steps = max(abs(y1 - y0), abs(x1 - x0), 1)
        thick = 2 if extent >= 6 else 1
        return {(min(size - 1, max(0, round(y0 + (y1 - y0) * t / steps) + dy)),
                 min(size - 1, max(0, round(x0 + (x1 - x0) * t / steps) + dx)))
                for t in range(steps + 1) for dy in range(thick) for dx in range(thick)}
    h, w = rng.randint(low, extent), rng.randint(low, extent)
    y, x = rng.randrange(size - h + 1), rng.randrange(size - w + 1)
    if kind == "rect":
        return {(yy, xx) for yy in range(y, y + h) for xx in range(x, x + w)}
    cy, cx, ry, rx = y + (h - 1) / 2, x + (w - 1) / 2, h / 2, w / 2
    def inside(yy, xx, shrink=0.0):
        return ((yy - cy) / max(0.5, ry - shrink)) ** 2 + ((xx - cx) / max(0.5, rx - shrink)) ** 2 <= 1
    pixels = {(yy, xx) for yy in range(y, y + h) for xx in range(x, x + w) if inside(yy, xx)}
    if kind == "ring" and min(h, w) >= 5:
        pixels -= {(yy, xx) for yy, xx in pixels if inside(yy, xx, shrink=1.5)}
    return pixels


def noise_grid(size, rng):
    """Pure grayscale noise: every pixel an independent random shade."""
    return [[rng.randrange(5) for _ in range(size)] for _ in range(size)]


def neighbors(grid, y, x):
    size = len(grid)
    return [grid[yy][xx] for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1))
            if 0 <= yy < size and 0 <= xx < size]


def noisy_pixels(grid):
    """Pixels that still read as noise: intermediate shades, or speckles unlike all neighbors."""
    return [(y, x) for y, row in enumerate(grid) for x, v in enumerate(row)
            if v not in (0, 4) or all(abs(v - n) >= 2 for n in neighbors(grid, y, x))]


def noise(grid):
    return len(noisy_pixels(grid))


def resolve(grid, y, x, rng):
    """Snap one noisy pixel: shades go to the nearest extreme, speckles to their neighbors' majority."""
    v = grid[y][x]
    around = neighbors(grid, y, x)
    dark = sum(n >= 2 for n in around) * 2 >= len(around)
    if v == 2:
        grid[y][x] = 4 if dark else 0
    elif v not in (0, 4):
        grid[y][x] = 4 if v > 2 else 0
    else:
        grid[y][x] = 4 if dark else 0


def anneal(grid, target, rng):
    """Forced denoising: resolve random noisy pixels until at most `target` remain."""
    result = [row.copy() for row in grid]
    remaining = noisy_pixels(result)
    while len(remaining) > target:
        y, x = remaining[rng.randrange(len(remaining))]
        resolve(result, y, x, rng)
        remaining = noisy_pixels(result)
    return result


def blend(noise_frame, clean, alpha):
    """The viewer's frame: the fixed noise fading into the clean estimate as alpha goes 0 -> 1."""
    return [[round(alpha * c + (1 - alpha) * n) for n, c in zip(noise_row, clean_row)]
            for noise_row, clean_row in zip(noise_frame, clean)]


def largest_component(grid):
    """Keep only the biggest 4-connected black region."""
    size = len(grid)
    seen, best = set(), []
    for start in ((y, x) for y in range(size) for x in range(size) if grid[y][x] == 4):
        if start in seen:
            continue
        component, stack = [], [start]
        seen.add(start)
        while stack:
            y, x = stack.pop()
            component.append((y, x))
            for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= yy < size and 0 <= xx < size and grid[yy][xx] == 4 and (yy, xx) not in seen:
                    seen.add((yy, xx))
                    stack.append((yy, xx))
        best = max(best, component, key=len)
    result = blank(size)
    for y, x in best:
        result[y][x] = 4
    return result


def blob_from_noise(noise_frame, rng):
    """A clean starting estimate read out of the noise: smooth it, keep the darkest 15-35% as ink,
    then keep the largest connected region. Different noise gives a different blob."""
    size = len(noise_frame)
    radius, ink = rng.randint(2, 3), rng.uniform(0.15, 0.35)
    means = []
    for y in range(size):
        for x in range(size):
            window = [noise_frame[yy][xx] for yy in range(y - radius, y + radius + 1)
                      for xx in range(x - radius, x + radius + 1) if 0 <= yy < size and 0 <= xx < size]
            means.append(sum(window) / len(window))
    threshold = sorted(means, reverse=True)[max(0, min(len(means) - 1, round(ink * len(means)) - 1))]
    grid = [[4 if means[y * size + x] >= threshold else 0 for x in range(size)] for y in range(size)]
    return anneal(largest_component(grid), 0, rng)


def composition(size, rng):
    """A clean starting estimate from one or two strokes on a white canvas."""
    grid = blank(size)
    for _ in range(rng.randint(1, 2)):
        for y, x in footprint(rng.choice(PRIMITIVES), size, max(MIN_EXTENT, round(size * 0.6)), rng):
            grid[y][x] = 4
    return grid


def denoise(grid, extent, rng):
    """Apply one local image-processing operator inside a random box; returns (grid, edit) or None."""
    size = len(grid)
    kind = rng.choice(DENOISERS)
    span = max(min(3, size), min(extent, size))
    h, w = rng.randint(min(3, size), span), rng.randint(min(3, size), span)
    y0, x0 = rng.randrange(size - h + 1), rng.randrange(size - w + 1)
    box = [(y, x) for y in range(y0, y0 + h) for x in range(x0, x0 + w)]
    result = [row.copy() for row in grid]
    if kind in ("smooth", "erode", "dilate"):
        pick = {"smooth": lambda vs: sorted(vs)[len(vs) // 2], "erode": min, "dilate": max}[kind]
        for y, x in box:
            window = [grid[yy][xx] for yy in range(y - 1, y + 2) for xx in range(x - 1, x + 2)
                      if 0 <= yy < size and 0 <= xx < size]
            result[y][x] = pick(window)
    elif kind == "fill":
        values = [grid[y][x] for y, x in box]
        majority = max(set(values), key=values.count)
        for y, x in box:
            result[y][x] = majority
    else:
        values = [grid[y][x] for y, x in box]
        dark = sum(v >= 2 for v in values) * 2 >= len(values)
        for y, x in box:
            v = grid[y][x]
            result[y][x] = 4 if v > 2 or (v == 2 and dark) else 0
    if result == grid:
        return None
    changed = sum(a != b for ra, rb in zip(grid, result) for a, b in zip(ra, rb))
    return result, dict(kind=kind, color=None, extent=extent, bbox=[y0, x0, y0 + h - 1, x0 + w - 1],
                        pixels=changed)


def content_box(grid):
    cells = [(y, x) for y, row in enumerate(grid) for x, v in enumerate(row) if v >= 2]
    if not cells:
        return None
    ys, xs = [y for y, _ in cells], [x for _, x in cells]
    return min(ys), min(xs), max(ys) + 1, max(xs) + 1


def transform(grid, rng):
    """Resample the drawn content into a shifted or rescaled box; returns (grid, edit)."""
    size = len(grid)
    box = content_box(grid)
    if box is None:
        return None
    y0, x0, y1, x1 = box
    h, w = y1 - y0, x1 - x0
    kind = rng.choice(TRANSFORMS)
    if kind == "shift":
        nh, nw = h, w
        dy, dx = rng.randint(-3, 3), rng.randint(-3, 3)
    else:
        nh = max(2, min(size, round(h * rng.uniform(0.7, 1.4))))
        nw = max(2, min(size, round(w * rng.uniform(0.7, 1.4))))
        dy, dx = (h - nh) // 2, (w - nw) // 2
    ny0 = min(size - nh, max(0, y0 + dy))
    nx0 = min(size - nw, max(0, x0 + dx))
    result = blank(size)
    for y in range(nh):
        for x in range(nw):
            result[ny0 + y][nx0 + x] = grid[y0 + y * h // nh][x0 + x * w // nw]
    if result == grid:
        return None
    changed = sum(a != b for ra, rb in zip(grid, result) for a, b in zip(ra, rb))
    return result, dict(kind=kind, color=None, extent=None, bbox=[ny0, nx0, ny0 + nh - 1, nx0 + nw - 1],
                        pixels=changed)


def mutate(grid, extent, rng, color=None):
    """Propose one edit: a denoise operator, a whole-image transform, or a black/white stroke.
    Returns (grid, edit) and always changes at least one pixel."""
    size = len(grid)
    roll = rng.random() if color is None else 1.0
    if roll < DENOISE_RATE:
        denoised = denoise(grid, extent, rng)
        if denoised is not None:
            return denoised
    elif roll < DENOISE_RATE + TRANSFORM_RATE and noise(grid) == 0:
        # Moving or rescaling only makes sense once a shape has formed; on noise it just smears.
        transformed = transform(grid, rng)
        if transformed is not None:
            return transformed
    kind = rng.choice(PRIMITIVES)
    pixels = footprint(kind, size, extent, rng)
    value = rng.choice((0, 4)) if color is None else color
    if all(grid[y][x] == value for y, x in pixels):
        value = 4 - value
    result = [row.copy() for row in grid]
    for y, x in pixels:
        result[y][x] = value
    ys, xs = [y for y, _ in pixels], [x for _, x in pixels]
    edit = dict(kind=kind, color="black" if value == 4 else "white", extent=extent,
                bbox=[min(ys), min(xs), max(ys), max(xs)], pixels=len(pixels))
    return result, edit


def propose(current, extent, rng, tries=10):
    """One edit to the clean estimate that still differs from `current` after cleanup."""
    for attempt in range(tries):
        grid, edit = mutate(current, extent, rng)
        grid = anneal(grid, 0, rng)
        if grid != current or attempt == tries - 1:
            edit["pixels"] = sum(a != b for ra, rb in zip(current, grid) for a, b in zip(ra, rb))
            return grid, edit


def render(grid):
    return "\n".join("".join(PALETTE[value] for value in row) for row in grid)


LEGEND = ("Each character is one square pixel, from light to dark: space=white, ░=light gray, "
          "▒=mid gray, ▓=dark gray, █=black. Newlines separate rows, top to bottom. "
          "Read each grid as a spatial image; preserve its whitespace.")


def jev_pick(client, prompt, candidates, model=MODEL, current=None):
    """Select the best candidate; with `current`, Jev may also choose to keep it (returns None)."""
    grids = {f"c{i:03}": render(grid) for i, grid in enumerate(candidates)}
    state = {"prompt": prompt, "legend": LEGEND, "candidates": grids}
    if current is None:
        instructions = ("Which grid in `candidates` best depicts `prompt`? "
                        "Choose the closest visual resemblance, even if all candidates are poor.")
        criteria = {key: None for key in grids}
    else:
        state["current"] = render(current)
        instructions = (
            "`current` is a work-in-progress pixel drawing of `prompt`. Each grid in `candidates` "
            "is `current` with exactly one shape added or erased. Compare each candidate against "
            "`current`: which one is the best next step toward a clear, recognizable depiction of "
            f"`prompt`? Prefer edits that improve the overall silhouette. Answer `{KEEP}` only if "
            "every candidate makes the drawing look less like `prompt` than `current` does."
        )
        criteria = {**{key: None for key in grids},
                    KEEP: "No candidate improves on `current`; leave it unchanged."}
    response = client.system_one(model=model, state=state,
                                 questions={"best": Choice(instructions=instructions, criteria=criteria)})
    answer = response.choices["best"]
    if answer.choice not in criteria:
        raise ValueError("Jev returned an unknown candidate ID")
    index = None if answer.choice == KEEP else list(grids).index(answer.choice)
    return index, {
        "model": response.model,
        "usage": response.usage.model_dump(),
        "answer": answer.model_dump(),
    }


LEVELS = [
    "Nothing like it: noise, scattered fragments, or a random blob",
    "Ambiguous: a blob or silhouette that could be many different things",
    "Probably the subject: a viewer would guess it, but it is distorted, oversized, cut off at the edges, "
    "or has stray marks",
    "Unmistakably the subject: well proportioned, fully inside the grid, clean outline, no stray marks",
]
CURRENT = "current"


def jev_score(client, prompt, candidates, model=MODEL, current=None):
    """Rate every frame independently in one request; returns ({id: expected score}, detail)."""
    frames = {f"c{i:03}": render(grid) for i, grid in enumerate(candidates)}
    if current is not None:
        frames = {CURRENT: render(current), **frames}
    response = client.system_one(
        model=model,
        state={"prompt": prompt, "legend": LEGEND, "frames": frames},
        questions={key: Score(
            instructions=f"Look only at the grid `frames.{key}` as a small black-and-white pixel image. "
                         f"How clearly does it depict `prompt`?",
            criteria=LEVELS,
        ) for key in frames},
    )
    answers = response.scores
    if set(answers) != set(frames):
        raise ValueError("Jev returned scores for unexpected frames")
    return {key: answers[key].score for key in frames}, {
        "model": response.model,
        "usage": response.usage.model_dump(),
        "scores": {key: {"score": a.score, "confidence": a.confidence} for key, a in answers.items()},
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


def run(client, *, prompt="a circle", size=20, steps=500, candidates=8, seed=0,
        model=MODEL, output, selector="score", allow_keep=True, margin=0.15, stop_at=None,
        confirm=True, patience=30):
    if size < 1 or steps < 1 or not 1 <= candidates <= 254:
        raise ValueError("Size and steps must be positive; candidates must be between 1 and 254")
    if not prompt.strip() or selector not in {"jev", "score", "random"}:
        raise ValueError("Provide a nonempty prompt and a jev, score, or random selector")
    if selector != "random" and client is None:
        raise ValueError("The jev and score selectors require a TypeSafe client")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    settings = dict(prompt=prompt, size=size, steps=steps, candidates=candidates,
                    seed=seed, model=None if selector == "random" else model, selector=selector,
                    generator="x0-prediction-v5", primitives=list(PRIMITIVES), transforms=list(TRANSFORMS),
                    denoisers=list(DENOISERS), denoise_rate=DENOISE_RATE, transform_rate=TRANSFORM_RATE,
                    min_extent=MIN_EXTENT, start="grayscale-noise",
                    levels=[0, 1, 2, 3, 4], allow_keep=allow_keep, show_current=selector == "score" or allow_keep,
                    margin=margin, stop_at=stop_at, patience=patience, confirm=confirm and selector == "score",
                    score_levels=LEVELS if selector == "score" else None,
                    schedule=schedule(steps, size), status="running", completed_steps=0)
    manifest = output / "run.json"
    manifest.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    rng, chooser = random.Random(seed), random.Random(seed)
    # x_T: the fixed noise this run starts from. `current` is the clean estimate x0 that Jev judges;
    # the viewer's frame blends the noise toward x0 as Jev's confidence in it grows.
    noise_frame = noise_grid(size, rng)
    current, keeps, current_score = None, 0, None
    frame, alpha, since_accept, horizon = noise_frame, 0.0, 0, max(1, min(steps, patience))
    started = time.perf_counter()
    try:
        with (output / "frames.md").open("w", encoding="utf-8") as frames, \
                (output / "steps.jsonl").open("w", encoding="utf-8") as log:
            frames.write(f"# {prompt}\n\n{size}×{size}, {steps} steps, seed {seed}, {selector}.\n\n")
            frames.write(f"## Step 0\n\n```text\n{render(noise_frame)}\n```\n\n")
            for step, extent in enumerate(settings["schedule"], 1):
                # After consecutive keeps, propose bigger strokes so Jev sees distinct options.
                extent = min(size, round(extent * 1.5 ** keeps)) if current is not None else 0
                if current is None:
                    # First estimates: half read out of the noise itself, half clean compositions.
                    proposals = [(blob_from_noise(noise_frame, rng) if i % 2 == 0 else composition(size, rng), None)
                                 for i in range(candidates)]
                else:
                    proposals = [propose(current, extent, rng) for _ in range(candidates)]
                rng.shuffle(proposals)
                options = [grid for grid, _ in proposals]
                request_started = time.perf_counter()
                if selector == "score":
                    scores, detail = jev_score(client, prompt, options, model, current=current)
                    best = max(range(len(options)), key=lambda i: scores[f"c{i:03}"])
                    best_score = scores[f"c{best:03}"]
                    selected, current_score = best, best_score
                    if current is not None:
                        if best_score <= scores[CURRENT] + margin:
                            selected, current_score = None, scores[CURRENT]
                        elif confirm:
                            # Second, independent judgment: a head-to-head Choice must agree.
                            pair = [current, options[best]]
                            flip = rng.random() < 0.5
                            winner, verdict = jev_pick(client, prompt, pair[::-1] if flip else pair, model)
                            detail["confirmation"] = dict(candidate=f"c{best:03}", candidate_first=flip, **verdict)
                            if (winner == 0) != flip:
                                selected, current_score = None, scores[CURRENT]
                elif selector == "jev":
                    reference = current if allow_keep else None
                    selected, detail = jev_pick(client, prompt, options, model, current=reference)
                else:
                    selected, detail = chooser.randrange(len(options)), {}
                kept = selected is None
                keeps = keeps + 1 if kept else 0
                chosen = current if kept else options[selected]
                changed_pixels = None if current is None else sum(
                    before != after for old_row, new_row in zip(current, chosen)
                    for before, after in zip(old_row, new_row)
                )
                current = chosen
                since_accept = 0 if not kept or step == 1 else since_accept + 1
                finished = step == steps or since_accept >= patience or (
                    stop_at is not None and current_score is not None and current_score >= stop_at)
                # Reveal: the noise fades into the estimate over the first `horizon` steps
                # (a run lasts at least `patience` steps), and is fully shown when the run ends.
                alpha = 1.0 if finished else max(alpha, min(1.0, step / horizon))
                frame = blend(noise_frame, current, alpha)
                elapsed = time.perf_counter() - request_started
                record = dict(step=step, extent=extent, changed_pixels=changed_pixels, alpha=alpha,
                              selected_index=selected, kept=kept, unchanged=kept, seconds=elapsed,
                              current_score=current_score, frame=render(frame), x0=render(current),
                              edits=[edit for _, edit in proposals],
                              candidates=[render(grid) for grid in options], **detail)
                log.write(json.dumps(record, ensure_ascii=False) + "\n")
                log.flush()
                frames.write(f"## Step {step}\n\n```text\n{render(frame)}\n```\n\n")
                frames.flush()
                settings["completed_steps"] = step
                manifest.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
                label = KEEP if kept else f"c{selected:03} {proposals[selected][1]['kind'] if proposals[selected][1] else 'init'}"
                if kept and "confirmation" in detail:
                    label = "keep (vetoed)"
                confidence = detail.get("answer", {}).get("confidence")
                status = (f"score {current_score:.2f} " if current_score is not None
                          else "" if confidence is None else f"conf {confidence:.2f} ")
                print(f"{step:03}/{steps}: {label:14} extent {extent:2} alpha {alpha:.2f} "
                      f"{status}{elapsed:.2f}s", flush=True)
                if finished and step < steps:
                    settings["stopped_early"] = True
                    settings["stop_reason"] = "plateau" if since_accept >= patience else "target"
                    break
        settings["status"] = "complete"
    except BaseException as exc:
        settings["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        settings["error_type"] = type(exc).__name__
        raise
    finally:
        settings["seconds"] = time.perf_counter() - started
        manifest.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        if current is not None:
            (output / "final.txt").write_text(render(frame) + "\n", encoding="utf-8")
            save_svg(frame, output / "final.svg")
            (output / "x0.txt").write_text(render(current) + "\n", encoding="utf-8")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", default="a circle")
    parser.add_argument("--size", type=int, default=20)
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--candidates", type=int, default=8, help="new grids per step (default: 8)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--selector", choices=["score", "jev", "random"], default="score",
                        help="score: rate every frame, accept only improvements (default); "
                             "jev: one Choice among edits plus keep; random: no API calls")
    parser.add_argument("--no-keep", dest="allow_keep", action="store_false",
                        help="jev selector only: hide the current frame and force a mutation every step")
    parser.add_argument("--margin", type=float, default=0.15,
                        help="score selector: a candidate must beat the current score by this much")
    parser.add_argument("--stop-at", type=float, help="score selector: stop once the current score reaches this")
    parser.add_argument("--patience", type=int, default=30,
                        help="stop after this many steps without an accepted improvement (default: 30)")
    parser.add_argument("--no-confirm", dest="confirm", action="store_false",
                        help="score selector: skip the head-to-head Choice that confirms each accepted edit")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.size < 1 or args.steps < 1 or not 1 <= args.candidates <= 254 or not args.prompt.strip():
        parser.error("Provide a nonempty prompt, positive size/steps, and 1–254 candidates")
    load_dotenv(Path(__file__).with_name(".env"))
    if args.selector != "random" and not os.environ.get("TYPESAFE_API_KEY", "").strip():
        parser.error("Set TYPESAFE_API_KEY in .env or your environment")
    args.output = args.output or Path("runs") / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    print(f"Saving run to {args.output.resolve()}", flush=True)
    try:
        with TypeSafeClient(timeout=60) if args.selector != "random" else nullcontext(None) as client:
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
