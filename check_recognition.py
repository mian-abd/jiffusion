"""Six live choices: can Jev distinguish simple character-grid shapes?"""

import json
from pathlib import Path
import random

from dotenv import load_dotenv
from typesafe_sdk import TypeSafeClient

from jiffusion import jev_pick, render


def main():
    load_dotenv(Path(__file__).with_name(".env"))
    noise_rng = random.Random(0)
    shapes = {
        "circle": [[4 if (x - 15.5)**2 + (y - 15.5)**2 <= 100 else 0
                    for x in range(32)] for y in range(32)],
        "cross": [[4 if abs(x - 15.5) < 2 or abs(y - 15.5) < 2 else 0
                   for x in range(32)] for y in range(32)],
        "stripes": [[4 if x // 4 % 2 else 0 for x in range(32)] for _ in range(32)],
        "noise": [[noise_rng.choice((0, 4)) for _ in range(32)] for _ in range(32)],
    }
    prompts = {"circle": "a dark circle on a white background",
               "cross": "a dark cross on a white background",
               "stripes": "vertical dark and white stripes"}
    records = []
    with TypeSafeClient(timeout=60) as client:
        for expected, prompt in prompts.items():
            for order in (list(shapes), list(reversed(shapes))):
                selected, detail = jev_pick(client, prompt, [shapes[name] for name in order])
                actual = order[selected]
                records.append(dict(prompt=prompt, expected=expected, actual=actual,
                                    order=order, correct=actual == expected, **detail))
                print(f"{expected}: selected {actual} ({'correct' if actual == expected else 'incorrect'})", flush=True)
    output = Path("runs/recognition")
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    (output / "shapes.md").write_text("\n".join(
        f"## {name}\n\n```text\n{render(grid)}\n```\n" for name, grid in shapes.items()
    ), encoding="utf-8")
    print(f"Correct: {sum(record['correct'] for record in records)}/{len(records)}")


if __name__ == "__main__":
    main()
