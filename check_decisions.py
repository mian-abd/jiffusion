"""Is Jev deciding on content? Re-ask the same candidate set in shuffled orders."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import random

from dotenv import load_dotenv
from typesafe_sdk import TypeSafeClient

from jiffusion import KEEP, initial_grid, jev_pick, mutate, render


def entropy(probabilities):
    return -sum(p * math.log2(p) for p in probabilities.values() if p > 0)


def trial(client, prompt, candidates, orders, rng, current=None):
    """Present the same grids in several orders; report agreement by grid identity."""
    winners, positions, confidences, entropies = [], [], [], []
    for _ in range(orders):
        order = list(range(len(candidates)))
        rng.shuffle(order)
        selected, detail = jev_pick(client, prompt, [candidates[i] for i in order], current=current)
        winners.append(KEEP if selected is None else order[selected])
        positions.append(selected)
        confidences.append(detail["answer"]["confidence"])
        entropies.append(entropy(detail["answer"]["probabilities"]))
    top_grid, top_count = Counter(winners).most_common(1)[0]
    top_pos, pos_count = Counter(positions).most_common(1)[0]
    return dict(winners=winners, positions=positions,
                grid_agreement=top_count / orders, position_agreement=pos_count / orders,
                consensus_grid=top_grid, mean_confidence=sum(confidences) / orders,
                mean_entropy_bits=sum(entropies) / orders,
                max_entropy_bits=math.log2(len(candidates)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", default="a circle")
    parser.add_argument("--size", type=int, default=20)
    parser.add_argument("--candidates", type=int, default=8)
    parser.add_argument("--orders", type=int, default=5, help="shuffled presentations per set")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    load_dotenv(Path(__file__).with_name(".env"))
    rng = random.Random(args.seed)

    # Scenario A: initial stroke grids (absolute judgment, no current frame).
    # Scenario B/C/D: strokes on one frame at extents 12/8/4, with `current` shown and `keep` offered.
    # Scenario E: a clean circle plus corrupted copies (a known-good gradient).
    base = initial_grid(args.size, rng)
    r2 = (args.size / 2 - 0.5)
    circle = [[4 if (x - r2) ** 2 + (y - r2) ** 2 <= (args.size * 0.3) ** 2 else 0
               for x in range(args.size)] for y in range(args.size)]

    def corrupt(grid, flips):
        result = [row.copy() for row in grid]
        for y, x in rng.sample([(y, x) for y in range(args.size) for x in range(args.size)], flips):
            result[y][x] = 4 - result[y][x]
        return result

    scenarios = {
        "A_initial": ([initial_grid(args.size, rng) for _ in range(args.candidates)], None),
        "B_extent12": ([mutate(base, 12, rng)[0] for _ in range(args.candidates)], base),
        "C_extent8": ([mutate(base, 8, rng)[0] for _ in range(args.candidates)], base),
        "D_extent4": ([mutate(base, 4, rng)[0] for _ in range(args.candidates)], base),
        "E_circle_gradient": ([circle] + [corrupt(circle, 8 * (i + 1)) for i in range(args.candidates - 1)], None),
    }

    results = {}
    with TypeSafeClient(timeout=60) as client:
        for name, (candidates, current) in scenarios.items():
            result = trial(client, args.prompt, candidates, args.orders, rng, current=current)
            result["candidates"] = [render(g) for g in candidates]
            results[name] = result
            print(f"{name:20} grid-agree {result['grid_agreement']:.2f}  "
                  f"pos-agree {result['position_agreement']:.2f}  "
                  f"conf {result['mean_confidence']:.2f}  "
                  f"entropy {result['mean_entropy_bits']:.2f}/{result['max_entropy_bits']:.2f} bits  "
                  f"winners {result['winners']} positions {result['positions']}", flush=True)

    output = Path("runs/decisions")
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
    print(f"\nChance grid-agreement for {args.candidates} candidates is about "
          f"{1 / args.candidates:.2f}; consistent content-based decisions score near 1.0.")
    print(f"Saved {output / 'results.json'}")


if __name__ == "__main__":
    main()
