"""Does Jev prefer a circle with fewer corrupted pixels, including tiny edits?"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import random

from dotenv import load_dotenv
from typesafe_sdk import TypeSafeClient

from jiffusion import jev_pick, render

FLIPS = [0, 1, 4, 16, 40, 80, 160]


def circle_ladder(seed, size=20):
    """Nested corruption of a known circle, used only for this diagnostic."""
    center = (size - 1) / 2
    clean = [[4 if (x-center)**2 + (y-center)**2 <= (size/3)**2 else 0
              for x in range(size)] for y in range(size)]
    positions = random.Random(seed).sample(range(size * size), max(FLIPS))
    grids = {}
    for count in FLIPS:
        grid = [row.copy() for row in clean]
        for position in positions[:count]:
            y, x = divmod(position, size)
            grid[y][x] = 4 - grid[y][x]
        grids[count] = grid
    return grids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs") / (
        "improvement-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    load_dotenv(Path(__file__).with_name(".env"))
    records = []
    with TypeSafeClient(timeout=60) as client, \
            (args.output / "results.jsonl").open("w", encoding="utf-8") as log, \
            (args.output / "fixtures.md").open("w", encoding="utf-8") as fixtures:
        for seed in range(3):
            grids = circle_ladder(seed)
            for count, grid in grids.items():
                fixtures.write(f"## Seed {seed}, {count} flipped pixels\n\n```text\n{render(grid)}\n```\n\n")
            for lower, higher in zip(FLIPS, FLIPS[1:]):
                order = [lower, higher]
                random.Random(seed * 1000 + higher).shuffle(order)
                for counts in (order, list(reversed(order))):
                    selected, detail = jev_pick(client, "a circle", [grids[n] for n in counts])
                    record = dict(seed=seed, fewer_flips=lower, more_flips=higher,
                                  candidate_flips=counts, selected_flips=counts[selected],
                                  correct=counts[selected] == lower, **detail)
                    records.append(record)
                    log.write(json.dumps(record) + "\n")
                    log.flush()
                correct = sum(r["correct"] for r in records[-2:])
                print(f"seed {seed}: {lower} vs {higher} corrupted pixels: {correct}/2", flush=True)
    summary = dict(
        calls=len(records), correct=sum(r["correct"] for r in records),
        pairs=[dict(fewer_flips=a, more_flips=b,
                    correct=sum(r["correct"] for r in records if r["fewer_flips"] == a), total=6)
               for a, b in zip(FLIPS, FLIPS[1:])],
    )
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Preferred fewer corrupted pixels: {summary['correct']}/{summary['calls']}")
    print(f"Results: {args.output.resolve()}")


if __name__ == "__main__":
    main()
