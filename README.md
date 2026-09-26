# Jiffusion

Generate grids as **five-level ASCII art** (`.:-=#`), ask Jev which looks most like **a circle**, change the brightness of a small patch on the winner, and repeat. One synchronous `for` loop; one Choice request per step.

```sh
uv sync
# Put TYPESAFE_API_KEY=... in .env (see .env.example).
uv run jiffusion.py
```

Defaults: **20×20 pixels, 750 steps, 16 new candidates per step**, seed `0`, prompt `"a circle"`, model `jev-1.13.0`. Use `--steps` for a shorter run. The full-generation DSPy experiment below uses two candidates. The script automatically loads this project's `.env`; existing environment variables take precedence. `.env` and generated runs are ignored by Git.

Each run gets a new directory under `runs/`:

- `frames.md`: all selected ASCII frames as code blocks, with their grid sizes.
- `final.svg`: the last frame rendered with square pixels and five brightness levels.
- `final.txt`: the last frame using `.:-=#`, from white to black.
- `steps.jsonl`: every candidate, grid size, patch size, selected index, changed-pixel count, Jev answer, actual model, usage, and request duration.
- `run.json`: configuration, resolution and edit schedules, exact legend and question, completion status, and elapsed time.

The first step selects among random 5×5 grids enlarged to 20×20, with all five brightness levels available. Later steps add a signed brightness delta to a square patch, clipping values to 0–4. The delta must change the patch's top-left pixel, guaranteeing a real edit even at the brightness endpoints. Each proposal starts from the same current frame, and candidate order is shuffled. **The unchanged frame is never offered: every iteration after initialization must select a mutation.** There are exactly 16 choices per call by default, including for the random baseline.

| Iterations (750-step run) | Patch size | Maximum brightness change per pixel |
| --- | --- | --- |
| 1 | Independent coarse random grids | Initialization |
| 2–75 | 4×4 | 4 levels |
| 76–300 | 2×2 | 2 levels |
| 301–750 | 1×1 | 1 level |

The phases scale with `--steps`: 10% for coarse edits, another 30% for medium edits, then 60% for fine edits. Each iteration makes one selection call in series, without sending earlier frames. The generator has no circle template or shape-specific rules. No annealing or scheduler framework.

```sh
uv run jiffusion.py "a circle" --seed 1 --output runs/circle-seed1
uv run jiffusion.py "a dark circle" --size 16 --steps 12 --candidates 8
uv run jiffusion.py --selector random --output runs/random-baseline
```

To compare choice counts with the current generator:

```sh
uv run jiffusion.py --candidates 8
uv run jiffusion.py --candidates 2
```

The 2-, 8-, and 16-choice experiments all completed with a different frame at every step after initialization. Two choices used fewer input tokens, but none of these runs produced a recognizable circle. See the [results and comparison images](validation.md).

For progressive resolution, use `--progressive`: at 750 steps, iterations 1–225 evolve an actual 5×5 grid, 226–450 evolve 10×10, and 451–750 evolve 20×20. The winner is enlarged with nearest-neighbor sampling at each transition, then mutated before being offered. Each mutation changes one pixel by default. Resolution stages use 30%, 30%, and 40% of the iterations; brightness limits still use the independent 10/30/60% schedule above. `--size` sets the final resolution and caps the earlier resolutions.

The ASCII experiment compares fixed and progressive resolution with both a short and explicit target, using the same one-pixel mutations and two choices throughout:

```sh
uv run jiffusion.py "a circle" --candidates 2 --patch-size 1
uv run jiffusion.py --explicit-circle --candidates 2 --patch-size 1
uv run jiffusion.py "a circle" --candidates 2 --progressive
uv run jiffusion.py --explicit-circle --candidates 2 --progressive
```

The earlier experiments used binary mutations; these commands now use the five-level generator. Add `--seed 0`, `--seed 1`, or `--seed 2` to compare noise layouts. The current default is 750 sequential calls. `--patch-size` overrides spatial patch sizes, not the brightness schedule. At resolution transitions, `changed_pixels` counts edits relative to the enlarged parent. Logs include both the permitted brightness delta and the largest actual change.

**Edit [prompts.py](prompts.py) to change the prompt text.** It contains `DEFAULT_PROMPT`, `EXPLICIT_CIRCLE_PROMPT` (selected with `--explicit-circle`), `ASCII_LEGEND`, `CHOICE_INSTRUCTIONS`, and the shared light-to-dark `PALETTE` (`.:-=#`). A positional CLI prompt overrides the default; `--explicit-circle` takes precedence if both are supplied. Each run saves the wording it actually used in `run.json`.

Every request sends the target as `state.prompt`, the ASCII strings under `state.candidates`, and this exact `state.legend`:

> Each candidate is ASCII art, not prose. Each character represents one square pixel: . is white, : is light gray, - is medium gray, = is dark gray, and # is black. Newlines separate rows, top to bottom. Read the arrangement of characters as a two-dimensional image.

The Choice question is the exact `CHOICE_INSTRUCTIONS` constant in [prompts.py](prompts.py). DSPy can optimize that constant with the workflow below; each run's `run.json` preserves the instruction it actually used.

Candidate IDs such as `c000` and `c001` are the available answers. Jev sees the current candidate set, without the previous frame or prior decisions. Earlier saved runs used spaces and Unicode blocks; new runs use ASCII dots and hashes and record that encoding in their manifests.

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

Clipart references live in [dataset/gold](dataset/gold), with one `ID-prompt.txt` file per drawing. The first line is the prompt and the remaining lines are the ASCII artwork. See [the dataset format](dataset/README.md).

Convert a raster image into a reference using the same five-character palette:

```sh
uv run image_to_ascii.py duck.png --prompt "a duck" --id 263
```

This writes `dataset/gold/263-a-duck.txt`, using a 20×20 canvas by default. The converter preserves aspect ratio, pads with white, handles transparency, and quantizes without dithering. It rejects IDs already used anywhere in the destination tree. Original user-supplied ASCII examples are preserved separately in [dataset/examples](dataset/examples).

The [250-shape dataset](dataset/gold/shapes-250) includes filled, outlined, negative-space, and pierced shapes. Each record is a prompt followed by a 20×20 grid using the five brightness levels. Browse the [contact sheet](dataset/gold/shapes-250/overview.png). Reproduce it in a fresh directory with `uv run generate_shapes.py --output-dir /tmp/shapes-250-rebuilt`.

## Optimize the shared instruction with DSPy

[optimize_prompts.py](optimize_prompts.py) uses DSPy **COPRO** to optimize only `CHOICE_INSTRUCTIONS` in [prompts.py](prompts.py). Vibe Proxy proposes instructions; the actual Jev model evaluates them through the same `Choice` request used by the generation loop. The palette, legend, target prompts, mutation algorithm, and forced-move rule stay fixed. DSPy is an optional dependency and is not part of the generation loop.

Start Vibe Proxy with its account connected at `http://localhost:8317`, then run:

```sh
uv sync --extra optimize
uv run --extra optimize optimize_prompts.py --prepare-only --output runs/dspy-data
uv run --extra optimize optimize_prompts.py --breadth 2 --depth 2 --output runs/dspy-first --apply
```

The proposer defaults to `openai/gpt-6-astra` through `http://localhost:8317/v1`. Override with `--proposal-model` or `--proposal-base-url`. The `openai/` prefix selects the OpenAI-compatible protocol; authentication belongs to Vibe Proxy. No Codex auth files are read or copied, and no separate OpenAI API key is required. If your proxy requires a key, set `VIBE_PROXY_API_KEY` in the ignored `.env` file. Jev continues using `TYPESAFE_API_KEY`. The proxy currently returns one completion for `n>1`, so the adapter makes individual proposal requests.

All 250 references produce 1,500 pairwise comparisons: light nested damage (4 versus 12 edited pixels), heavy damage (40 versus 120), and correct versus incorrect requested style. Every pair appears in both candidate orders. Both damage candidates are already imperfect. The metric is selection accuracy; Jev never receives the original reference, damage counts, correct answer, filename, or family metadata.

| Split | Entire shape families | Comparisons |
| --- | --- | --- |
| Training | triangle, pentagon, hexagon, star, cross | 750 |
| Validation | circle, ellipse | 300 |
| Final test | square, rectangle, diamond | 450 |

Every source's styles, positions, and corruptions stay together. Related round shapes and quadrilaterals also stay together. COPRO sees only the initial instruction and aggregate training scores, never drawings or target names. Its proposal policy forbids shape-specific rules, examples, templates, and fixed position/color preferences. A runtime guard rejects obvious shape names and templates, and the Jev predictor refuses all demonstrations. The guard catches common violations; it cannot prove an arbitrary instruction generalizes.

The best legal training candidate is compared with the baseline on validation. Only a strict validation improvement selects the candidate. The choice is saved **before** the final test. Test results never feed back into proposals or candidate selection, but they can veto deployment: `--apply` replaces just the instruction constant only when validation **and** final-test accuracy improve. The selected candidate is always written to the run's `prompts.py`, even when deployment is withheld. Review its wording and per-family results in `report.json`. `selector.json` saves the DSPy signature without demonstrations or credentials; the run also contains exact splits, proposals, selection decisions, and Jev requests/answers. Existing output directories are refused. Successful duplicate requests are cached within a run; failures abort instead of counting as wrong answers. Interrupted runs preserve request logs but do not resume.

`--breadth` controls proposals per round (including the baseline in round one), `--depth` controls rounds, and `--threads` controls evaluation concurrency. The defaults are 3, 2, and 4. `--max-jev-calls` caps evaluation requests (default 10,000, excluding SDK retries); proposal calls consume the proxy account's allowance. `--seed` controls synthetic damage, not remote-model determinism.

These labels are **synthetic reconstruction and style preferences**, not human judgments of arbitrary clipart. Lower pixel damage is a useful proxy but is not always more recognizable. Mirrored pairs and source variants are correlated. A held-out-family gain supports transfer within this primitive dataset; it does not establish that a 500-step run from noise will converge, or that gains transfer to 8 or 16 choices. Keep this final test fixed and avoid repeatedly tuning against its results.

The [first live run](dataset/dspy-vibe-001-report.json) made 3,750 Jev calls. Validation improved from 271/300 to 274/300, but the held-out result changed from 408/450 to 406/450. The original production instruction remains active. This small difference does not establish a generalization gain. The deployment veto was added after reviewing this first result; no further prompt search used the test results.

Run the complete offline suite, including the DSPy adapter, with:

```sh
uv run --extra optimize python -m unittest discover -s tests -v
```

References: [DSPy COPRO implementation](https://github.com/stanfordnlp/dspy/blob/main/dspy/teleprompt/copro_optimizer.py), [Vibe Proxy setup](https://github.com/automazeio/vibeproxy/blob/main/FACTORY_SETUP.md), [TypeSafe Choice](https://docs.typesafe.ai/primitives/choice).

## Optimize complete generation from noise

[optimize_diffusion.py](optimize_diffusion.py) makes **a full 750-step generation** the unit of evaluation. Each instruction candidate starts from random coarse pixels and uses the existing for loop: make two mutations, ask Jev, take the winner, repeat. Every call uses the candidate instruction. The unchanged frame is never offered, no gold image guides mutations, and each trajectory makes its calls in series. Independent trajectories may run concurrently.

```sh
uv run --extra optimize optimize_diffusion.py --output runs/diffusion-750
```

Defaults: fixed 20×20, 750 steps, two choices, standard shrinking patch schedule, COPRO breadth 2/depth 2, five concurrent trajectories. At 750 steps the patch schedule is initialization, 74 edits at 4×4, 225 at 2×2, and 450 single-pixel edits. Vibe Proxy supplies proposals as above. A 24,000-call budget covers this pilot's maximum of 22,500 logical Jev calls; SDK retries are additional. Random-selection controls make no API calls. Successful identical trajectories are cached within a run. Existing output directories are refused; partial trajectories keep their normal logs but resume is not implemented.

The initial pilot uses **filled shapes**: five training families with seed 0, two validation families with seed 1, and three test families with seed 2, using the same family split as above. Baseline and candidate get identical RNG seeds for each target. Each target has five clean position/size variants used only by the evaluator. Extend coverage with `--styles filled outline negative negative-outline hole` and increase `--max-jev-calls` accordingly.

The objective is final **soft foreground intersection-over-union (IoU)** against the best of those five references. It ranges from 0 to 1 and is not classification accuracy. Foreground strength is brightness distance from the reference background, scaled to 0–1. The score sums per-pixel minima divided by per-pixel maxima, preserving all five levels without thresholding. Empty background earns zero; excess foreground lowers the score. Jev and the proposer never receive the reference images. It remains a geometric proxy: unmatched placements can be penalized, and overlap does not prove the image is recognizable.

COPRO sees only instructions and aggregate training scores. The best training candidate is fixed, checked on validation, and reported on the test even if validation rejects it. The test is never fed back into prompt search. `report.json` records per-target results and random controls; `candidate-prompts.py` holds the proposed instruction; `finals.png` shows reference, original-prompt output, candidate output, and random control side by side. Each trajectory has its own `frames.md`, `steps.jsonl`, and final text/SVG. This tool exports the candidate without changing the production prompt. Review the images as well as the scores before adopting it; one seed per target is an initial experiment, not a robust generalization estimate.
