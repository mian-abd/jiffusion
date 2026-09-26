Validation — September 26, 2026
===============================

x₀-prediction loop (`x0-prediction-v5`, current default)
--------------------------------------------------------

Grayscale noise start; Jev scores the clean estimate and 8 candidate edits per request (Score, 4 levels), a candidate must beat the current score by 0.15 and then win a head-to-head Choice against it; runs stop after 30 (circle) / 40 (duck) steps without an accepted edit.

| Prompt | Seed | Steps | Stop | Final score | Accepted | Passed Score | Vetoed by Choice | Input tokens | Wall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| a circle | 0 | 33 | plateau | 2.67 | 1 | 3 | 2 | 118,920 | 5 s |
| a circle | 1 | 75 | plateau | 2.57 | 5 | 5 | 0 | 315,831 | 10 s |
| a circle | 2 | 80 | plateau | 2.31 | 11 | 21 | 10 | 334,043 | 12 s |
| a duck (24×24) | 0 | 150 | max steps | 2.12 | 32 | 67 | 35 | 463,735 | 27 s |
| a duck (24×24) | 1 | 150 | max steps | 2.05 | 33 | 51 | 18 | 767,050 | 26 s |

Seeds 0 and 1 of `a circle` converge to a clean solid circle read out of the noise blob ([docs/v8-circle.png](docs/v8-circle.png)); seed 2 ends as an oversized blob in a corner. Both ducks are bird-like silhouettes that Jev rates "probably the subject" but not a duck ([docs/v8-duck.png](docs/v8-duck.png)). Wall time here excludes the earlier sequential experiments' overhead; each Jev request took 0.2–0.4 s.

Across all runs, 40–50% of the edits that passed the Score margin were vetoed by the independent head-to-head Choice. Re-scoring the same frame varies by about ±0.15, so the Score alone would have accepted roughly twice as many edits, many of them neutral shifts. **23 offline tests pass.**

Decision-consistency diagnostic (`check_decisions.py`)
------------------------------------------------------

Same 8 candidates presented in 5 shuffled orders; a content-based judge should pick the same grid each time (chance ≈ 0.12), a position-biased one the same slot.

| Scenario | Grid agreement | Position agreement | Mean confidence |
| --- | --- | --- | --- |
| Old generator, 4×4 patches | 1.00 | 0.40 | 0.24 |
| Old generator, 2×2 patches | 0.20 | **0.80** | 0.19 |
| Old generator, 1-pixel flips | 0.40 | 0.40 | 0.14 |
| Strokes, extent 12, current shown | 0.80 | 0.40 | 0.24 |
| Strokes, extent 8, current shown | 0.80 | 0.40 | 0.16 |
| Strokes, extent 4, current shown | 0.80 | 0.20 | 0.10 |
| Clean circle vs corrupted copies | 1.00 | 0.20–0.60 | 0.73–0.77 |

This is what motivated the design: below a ~4 px footprint Jev's choices track position, not content, and the original schedule spent 450 of 500 steps there. Showing the current frame and offering `keep` restored content-consistent decisions at every stroke size.

Intermediate designs (kept as evidence)
---------------------------------------

- **Strokes + Choice with `keep`** (`primitives-v2`): 60 steps from a blank canvas produced coherent shapes for the first time, but Jev kept accepting larger ellipses until the blob filled the canvas ([docs/v2-circle-finals.png](docs/v2-circle-finals.png)). `--no-keep` and random baselines produced noise.
- **Score gate without confirmation**: fixed over-growth (clean ellipse, 3 accepts in 60 steps) but was exploited by content-neutral shifts because of score noise.
- **Score + head-to-head, blank-canvas start** (`primitives-v3`): clean stable ellipses ([docs/v4-circle.png](docs/v4-circle.png)); ducks were blobs with a beak-like protrusion.
- **Forced pixel denoising from noise** (`denoise-v4`): a shrinking noise budget resolved to random blob textures that Jev then had to carve; results were worse than the blank-canvas start, which led to searching in x₀ space and blending for the viewer.

Earlier experiments (original pixel-flip generator)
---------------------------------------------------

Experiment: **required mutations with 16, 8, and 2 choices per call**. Each run used a 20×20 grid, 500 sequential Jev calls, prompt `a circle`, seed 0, and the same coarse binary initialization and shrinking patch schedule. The unchanged current frame is no longer a candidate. The CLI default remains 16 choices; 8 and 2 are explicit experiments.

| Choices | Steps | Wall time | Input tokens | Unchanged transitions | Selected first option |
| --- | --- | --- | --- | --- | --- |
| 16 | 500 | 58.23 s | 2,386,629 | 0/499 | 430/500 |
| 8 | 500 | 55.22 s | 1,251,013 | 0/499 | 313/500 |
| 2 | 500 | 56.18 s | 449,248 | 0/499 | 114/500 |

**None produced a recognizable circle.** Visual inspection shows the initial broad regions breaking into speckled patterns as the edits shrink. Two choices substantially reduced input-token usage, but did not visibly improve the result. The three runs took similar time. Selection frequencies alone do not isolate an ordering or candidate-ID effect. These are single-seed exploratory runs; changing the candidate count also changes the generated pools and subsequent random-number sequence.

The logs confirm exactly the requested number of candidates on all 1,500 live calls. For all 1,497 transitions after initialization, no offered candidate equaled the previous frame and the selected frame changed at least one pixel. All three corresponding 500-step random baselines also completed and passed these checks. **10 offline tests passed**, including the regression that the current frame is never offered.

Local artifacts: [final frames](runs/forced-choice-finals.png), [progress and random baselines](runs/forced-choice-comparison.png), [summary](runs/forced-choice-summary.json), [2-choice frames](runs/circle-forced-2-seed0/frames.md), [2-choice decisions](runs/circle-forced-2-seed0/steps.jsonl), [8-choice decisions](runs/circle-forced-8-seed0/steps.jsonl), and [16-choice decisions](runs/circle-forced-mutations-seed0/steps.jsonl).

Reproduce with `uv run jiffusion.py --candidates 2 --seed 0` (or `8` / `16`). Each command creates a separate run directory.

Earlier experiment, allowing the current frame to remain unchanged: **coarse binary initialization and shrinking patch edits** (`binary-patches-v1`). All five proposed changes were implemented: random 5×5 grids enlarged to 20×20, black and white only, uniform square edits, a short coarse phase followed by fine edits, and a separate diagnostic of incremental judgments. These historical runs used prompt `a circle`, 500 sequential calls, and 16 new candidates plus the unchanged frame after initialization.

All three seeds completed. The frames have larger coherent regions than the previous method, but **none shows a clear circle**. They remain close to their starting blocks; most proposed edits are rejected. The random-selector baselines became substantially more speckled. Reduced visual noise is not evidence of successful circle generation.

| Seed | Steps | Wall time | Input tokens | Kept current frame | Kept during first 50 steps |
| --- | --- | --- | --- | --- | --- |
| 0 | 500 | 59.23 s | 2,404,148 | 454 | 43 |
| 1 | 500 | 60.30 s | 2,609,631 | 453 | 47 |
| 2 | 500 | 58.54 s | 2,251,813 | 478 | 47 |

The circle-corruption diagnostic preferred fewer flipped pixels in **32/36 comparisons**. Three nested noise layouts were tested, with each adjacent pair presented in both orders using the same `jev_pick` function as generation. The reference circle is used only in this diagnostic, never in the search.

| Flipped pixels compared | Cleaner candidate selected |
| --- | --- |
| 0 vs 1 | 4/6 |
| 1 vs 4 | 6/6 |
| 4 vs 16 | 6/6 |
| 16 vs 40 | 6/6 |
| 40 vs 80 | 6/6 |
| 80 vs 160 | 4/6 |

This small diagnostic supports some sensitivity to corruption, with weaknesses at single-pixel differences and heavy corruption. It does not establish a reliable search signal between arbitrary block patterns. The production runs still stall, even with smaller mutations.

**10 offline tests passed.** Diagnostic fixtures were checked for exact nested corruption. All 1,500 live search steps were checked for binary candidates and bounded edits; every selected edit after step 200 changed at most one pixel. Three 500-step random baselines also completed.

Local artifacts: [before/after final frames](runs/circle-patches-before-after.png), [three seeds over time beside random baselines](runs/circle-patches-comparison.png), [seed 0 frames](runs/circle-patches-seed0/frames.md), [seed 0 decisions](runs/circle-patches-seed0/steps.jsonl), [diagnostic summary](runs/improvement-binary-patches-v1/summary.json), [diagnostic decisions](runs/improvement-binary-patches-v1/results.jsonl), and [diagnostic fixtures](runs/improvement-binary-patches-v1/fixtures.md).

Earlier experiment with scattered grayscale edits: **20×20 pixels, 500 sequential iterations, prompt `a circle`, 16 new candidates per iteration**, seed 0. This full run completed in **76.54 seconds**, using **3,798,567 input tokens** in total (about 7,597 per call). Jev retained the current frame 280 times and selected the first option 77 times. Visual inspection still shows noise, without a recognizable circle. The 500-step random baseline also completed.

Local artifacts: [progress comparison](runs/circle-20x20-500-comparison.png), [all 500 frames](runs/circle-20x20-500-seed0/frames.md), [final square-pixel frame](runs/circle-20x20-500-seed0/final.svg), [candidate/decision log](runs/circle-20x20-500-seed0/steps.jsonl). The preceding 20×20 duck run was interrupted at step 102 when the prompt changed; its partial artifacts remain saved separately.

The eight offline tests passed after the grid and iteration changes. The default CLI settings and 500 saved baseline frames were also checked. The earlier 32×32, 50-step experiment is preserved below as historical evidence.

The implemented loop runs end to end against Jev with the requested **32×32 grid, 50 steps, and prompt `a duck`**. These runs did **not** produce a recognizable duck. Visual inspection of three seeds showed no clear improvement over random selection.

| Selector | Seed | Steps completed | Wall time | Input tokens | Kept current frame | Selected first option |
| --- | --- | --- | --- | --- | --- | --- |
| Jev | 0 | 50 | 12.43 s | 903,229 | 14 | 39 |
| Jev | 1 | 50 | 12.45 s | 904,865 | 12 | 39 |
| Jev | 2 | 50 | 12.20 s | 903,539 | 12 | 41 |
| Random | 0 | 50 | 0.25 s | 0 | 2 | 2 |
| Random | 1 | 50 | 0.23 s | 0 | 4 | 8 |
| Random | 2 | 50 | 0.22 s | 0 | 2 | 2 |

All Jev responses reported `jev-1.13.0`. Each run used 16 new candidates per step, plus the current frame after step 1. Candidate order was shuffled before selection. The strong preference for the first option on noise is a limitation of this experiment; confidence should not be read as progress toward a duck. The test does not isolate whether that preference comes from position, the ID, or another cause.

The same selector correctly identified a circle, cross, and vertical stripes in both forward and reversed candidate orders: **6/6 live checks**. Recognizing existing shapes is easier than finding a useful direction among noise mutations. These fixtures are never used to initialize or guide generation.

**8 offline tests passed**, covering grid shape and values, exact mutation counts and distances (including intensity boundaries), immutable parent grids, whitespace preservation, the 50-step schedule, Choice ID mapping, previous-winner inclusion, frame/log output, failure preservation, output-directory protection, and reproducible random baselines.

A preliminary request with 33 random 32×32 grids returned `400 max_tokens_exceeded`. The 16-candidate configuration completed all runs. The original 32-candidate proposal was reduced to preserve one API call per step without batching machinery.

Local artifacts from this validation (under Git-ignored `runs/`):

- [Final frames beside random baselines](runs/duck-comparison.png)
- [Default run's 50 frames](runs/duck-jev-seed0/frames.md)
- [Default run's square-pixel final frame](runs/duck-jev-seed0/final.svg)
- [Default run's exact candidates and decisions](runs/duck-jev-seed0/steps.jsonl)
- [Recognition results](runs/recognition/results.json)

Reproduce a run with `uv run jiffusion.py --seed 0`. The random generator is seeded, but remote model decisions can change. Current scope is the simple working experiment; generating a recognizable duck remains unproven.
