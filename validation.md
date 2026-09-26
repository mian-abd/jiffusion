MVP validation — September 26, 2026
==================================

Latest prompt experiment: [DSPy instruction optimization](#dspy-instruction-optimization-2026-09-26). The candidate improved validation but did not improve the held-out test, so the original production instruction remains active.

Earlier generation experiments: **progressive resolution and an explicit circle prompt, using ASCII art** (`binary-patches-v2`, `ascii-dot-hash-v1`). Tested all four combinations with seeds 0, 1, and 2: 12 live runs, each with 500 sequential calls and exactly two choices. Every proposed mutation flips one pixel at the current resolution. The two resolution modes ran concurrently, with calls inside each run remaining sequential.

- Fixed resolution: 20×20 throughout, initialized from an enlarged random 5×5 grid.
- Progressive resolution: 150 steps at 5×5, 150 at 10×10, and 200 at 20×20. Enlarge the previous winner before generating mutations at each boundary.
- Short target: `a circle`.
- Explicit target: `One filled black disk on a white background, with a smooth round boundary.`
- Both modes use the same ASCII encoding (`.` white, `#` black), legend, selection question, and one-pixel mutations. This comparison isolates the resolution schedule and target wording. Earlier Unicode runs also differed in encoding and/or mutation schedule.

| Resolution | Target | Completed runs | Mean wall time per run | Mean input tokens per run | First option selected |
| --- | --- | --- | --- | --- | --- |
| Fixed | Short | 3/3 | 54.89 s | 361,342 | 436/1,500 |
| Fixed | Explicit | 3/3 | 55.99 s | 366,337 | 131/1,500 |
| Progressive | Short | 3/3 | 55.86 s | 282,196 | 658/1,500 |
| Progressive | Explicit | 3/3 | 55.62 s | 288,027 | 569/1,500 |

**None of the 12 final images shows a clear circle.** Intermediate images retain broad regions during coarse phases, but the final frames remain fragmented. Visual inspection does not show a clear advantage over the six corresponding random-selector controls. Progressive resolution reduced input-token usage by roughly 22%, without producing the target shape. The explicit prompt did not visibly solve the problem. The fixed-resolution explicit runs selected the second option in 1,369/1,500 calls despite shuffled candidates; this remains a reason to test ordering separately.

All 18 runs, including random controls, completed. The logs were checked for exact resolution boundaries, binary ASCII grids, exactly two candidates, and exactly one changed pixel for every candidate after initialization, relative to the enlarged parent at transitions. No unchanged parent was offered. All 6,000 live responses reported `jev-1.13.0`. **12 offline tests passed**, and both CLI prompt modes were checked against the constants.

The grid search's authored prompt text is centralized in [prompts.py](prompts.py): both target prompts, the ASCII legend, and the Choice instruction. Every run manifest preserves the exact text used. These runs used the binary dot/hash legend; the later image converter extends the current legend to describe all five brightness levels. Use `--explicit-circle` to select the detailed target.

Local artifacts: [all final frames beside random controls](runs/ascii-experiments-finals.png), [seed 0 progress](runs/ascii-experiments-progress.png), [per-run summary](runs/ascii-experiments-summary.json), [progressive explicit seed 0 manifest](runs/ascii-progressive-explicit-seed0/run.json), and [its exact candidates and decisions](runs/ascii-progressive-explicit-seed0/steps.jsonl). The README contains commands for all four configurations.

Earlier experiment: **required mutations with 16, 8, and 2 choices per call**. Each run used a 20×20 grid, 500 sequential Jev calls, prompt `a circle`, seed 0, and the same coarse binary initialization and shrinking patch schedule. The unchanged current frame is no longer a candidate. The CLI default remains 16 choices; 8 and 2 are explicit experiments.

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
## DSPy instruction optimization, 2026-09-26

The first live DSPy COPRO run used `openai/gpt-6-astra` through Vibe Proxy at
`http://localhost:8317/v1` to propose shared selection instructions, and
`jev-1.13.0` to evaluate them. Breadth 2, depth 2, corruption seed 0, four
evaluation workers. Three generated proposals plus the original instruction
were considered; one proposal failed the field-reference guard and made no Jev
calls. The run made 3,750 Jev evaluation calls.

| Split | Original | Validation-selected candidate |
| --- | --- | --- |
| Training: five families, 750 comparisons | 659/750 (87.9%) | 671/750 (89.5%) |
| Validation: circle and ellipse, 300 comparisons | 271/300 (90.3%) | 274/300 (91.3%) |
| Test: square, rectangle, diamond, 450 comparisons | 408/450 (90.7%) | 406/450 (90.2%) |

The candidate was frozen using training/validation before the test ran. No
drawings, target names, or demonstrations were sent to the proposal model. The
selected instruction contains general spatial/tonal comparison guidance and no
named shapes or special cases. The baseline and candidate both scored 150/150 on
the held-out local-damage comparisons; the test difference came from style
comparisons (121/150 versus 119/150). Both-orders-correct accuracy changed from
89.8% to 88.0% on the test.

This run does **not** establish a generalization gain. After seeing this result,
we restored the original production instruction and added a deployment veto:
`--apply` now requires gains on both validation and the final test. This veto was
added after the first run, not specified before it. The test was not used for any
further prompt search. Future tuning should use new held-out data or a separate
evaluation protocol, rather than repeatedly tuning against this test.

The preferences are synthetic: lower nested pixel damage, or the requested style
versus a mismatched style of the same shape. They are not human semantic labels;
source variants and mirrored candidate orders are correlated. This evaluation
uses two choices and does not demonstrate convergence of the random-mutation
generation loop.

The [saved report](dataset/dspy-vibe-001-report.json) contains the exact proposed
instructions, family/style/damage breakdowns, dataset hash, and configuration.
Detailed requests, fixed splits, and the candidate `prompts.py` remain under
`runs/dspy-vibe-001/` (ignored by Git). The full offline suite has 30 passing tests.
