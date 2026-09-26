# Jiffusion

Generate coarse black-and-white grids, ask Jev which looks most like **a circle**, edit a small square on the winner, and repeat. One synchronous `for` loop; one Choice request per step.

```sh
uv sync
# Put TYPESAFE_API_KEY=... in .env (see .env.example).
uv run jiffusion.py
```

Defaults: **20×20 pixels, 500 steps, 16 new candidates per step**, seed `0`, prompt `"a circle"`, model `jev-1.13.0`. Use `--steps` for a shorter run. The script automatically loads this project's `.env`; existing environment variables take precedence. `.env` and generated runs are ignored by Git.

Each run gets a new directory under `runs/`:

- `frames.md`: all selected frames as whitespace-preserving code blocks.
- `final.svg`: the last frame rendered with square pixels, white through black.
- `final.txt`: the last frame using spaces (white) and `█` (black).
- `steps.jsonl`: every candidate, patch size, selected index, changed-pixel count, Jev answer, actual model, usage, and request duration.
- `run.json`: configuration, the full schedule, completion status, and elapsed time.

The first step selects among random 5×5 black-and-white grids enlarged to 20×20, so the starting images have broad regions. Later steps paint one square uniformly black or white. The chosen color differs from the pixel at the square's top-left corner, guaranteeing a real edit. Each proposal starts from the same current frame, and candidate order is shuffled. **The unchanged frame is never offered: every iteration after initialization must select a mutation.** There are exactly 16 choices per call by default, including for the random baseline.

| Iterations (500-step run) | New candidate edits |
| --- | --- |
| 1 | Independent coarse random grids |
| 2–50 | Paint one 4×4 square (1–16 changed pixels) |
| 51–200 | Paint one 2×2 square (1–4 changed pixels) |
| 201–500 | Flip one pixel |

The phases scale with `--steps`: 10% for coarse edits, another 30% for medium edits, then 60% for fine edits. Each iteration makes one selection call in series, without sending earlier frames. The generator has no circle template or shape-specific rules. No annealing or scheduler framework.

```sh
uv run jiffusion.py "a circle" --seed 1 --output runs/circle-seed1
uv run jiffusion.py "a dark circle" --size 16 --steps 12 --candidates 8
uv run jiffusion.py --selector random --output runs/random-baseline
```

To repeat the 500-step choice-count experiments:

```sh
uv run jiffusion.py --candidates 8
uv run jiffusion.py --candidates 2
```

The 2-, 8-, and 16-choice experiments all completed with a different frame at every step after initialization. Two choices used fewer input tokens, but none of these runs produced a recognizable circle. See the [results and comparison images](validation.md).

`--selector random` uses the same generator and schedule without making API calls. Existing output directories are never overwritten. Completed steps are flushed to disk and the last selected frame is exported if a later call fails or you interrupt the run. Restarting creates a new run; resume is not implemented. The SDK handles transient retries.

In the earlier 32×32 experiment, a live request with 33 grids exceeded Jev's context budget. Increasing `--size` or `--candidates` can still exceed the limit. The CLI reports the error and asks you to reduce one of them. Choice accepts at most 255 options, and state plus the question must fit 32k tokens. [TypeSafe limits](https://docs.typesafe.ai/models), [Choice API](https://docs.typesafe.ai/primitives/choice)

Checks:

```sh
uv run python -m unittest discover -s tests -v  # offline
uv run check_recognition.py                  # six live shape-recognition requests
uv run check_improvement.py                  # 36 live comparisons of corrupted circles
```

The live check asks Jev to distinguish a circle, cross, stripes, and noise in two candidate orders, using the same selector as the search. Its fixtures are only for evaluation; generation starts from noise. A passing recognition check does not establish that random mutation search will draw a recognizable circle. The seed controls local randomness, not remote model determinism. Jev's confidence is a selection statistic, not a measure of image quality.

`check_improvement.py` uses a known 20×20 circle with 0, 1, 4, 16, 40, 80, or 160 flipped pixels. It compares adjacent corruption levels across three noise layouts and both candidate orders. Jev sees only the grids and prompt, never the corruption labels. Fixtures and results go into a new `runs/improvement-*` directory. These reference circles are only used in the diagnostic.

[Validation results and earlier experiments](validation.md).
