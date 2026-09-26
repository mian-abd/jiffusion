Jiffusion: current experiment
============================

Keep one synchronous `for` loop: generate random candidates, ask Jev to select the closest visual match, and use that winner for the next iteration.

Defaults: a **20×20** output, **750 sequential iterations**, **16 new candidates** per iteration, prompt **“a circle”**, seed 0, and model `jev-1.13.0`. Each request contains only the current candidate set. Full-generation DSPy optimization uses two candidates and scores the final image after all 750 steps; reference artwork is evaluation-only. Earlier 500-step experiments are documented below.

Earlier binary experiments tested **progressive resolution** and **a more explicit target prompt**. They ran all four combinations of fixed/progressive resolution and short/explicit prompt, with seeds 0, 1, and 2. Each run had two choices, 500 sequential calls, and one-pixel mutations. The current experiment instead uses all five levels and optimizes the final image of a 750-step generation.

- Fixed resolution: 20×20 for all 500 steps, initialized from an enlarged random 5×5 grid.
- Progressive resolution: 5×5 for steps 1–150, 10×10 for 151–300, and 20×20 for 301–500. Enlarge the selected frame with nearest-neighbor sampling before generating new mutations at a phase boundary.
- Short target: `a circle`.
- Explicit target: `One filled black disk on a white background, with a smooth round boundary.`
- Each request explicitly describes the candidates as ASCII art, using `.` for white and `#` for black. Store the exact legend and Choice instructions in the run manifest.
- Keep the grid search's target prompts, ASCII legend, and Choice instructions together in `prompts.py`. Use `--explicit-circle` to select the explicit constant, or pass a custom target as the positional CLI argument.
- Run one random-selector control per resolution mode and seed; its behavior is independent of prompt wording.

Every candidate after initialization must differ from the current frame, including after enlargement. Do not offer the unchanged frame. Preserve the simple loop and the same Jev selector; no circle template or geometry reward is introduced. Compare final images and intermediate frames against the controls, and report that visual assessment separately from successful execution.

The current generator:

1. **Coarse initialization.** Each starting candidate is a random 5×5 five-level grid enlarged to 20×20 with nearest-neighbor sampling.
2. **Five brightness levels.** Store intensities 0–4 and render them as `.:-=#`, from white to black.
3. **Connected brightness edits.** A mutation adds a signed brightness delta to one randomly placed square, clipping at 0 and 4. Its top-left pixel must change. Every candidate starts from a copy of the same current grid.
4. **Reduce area and brightness changes.** Step 1 initializes. Steps 2–75 use 4×4 patches and deltas up to 4 levels; 76–300 use 2×2 patches and deltas up to 2; 301–750 use single pixels and deltas of 1. Every proposed mutation obeys its brightness limit.
5. **Check incremental judgment.** Independently compare a reference circle at increasing corruption levels, reversing the candidate order. This tests whether Jev recognizes small improvements; knowing the names of clean shapes alone is insufficient.

The core loop stays simple (pseudocode):

```python
current = None
for patch_size, brightness_limit in zip(schedule(750), brightness_schedule(750)):
    candidates = [
        random_grid(20, rng) if current is None
        else mutate(current, patch_size, rng, brightness_limit)
        for _ in range(16)
    ]
    rng.shuffle(candidates)
    current = jev_pick(prompt, candidates)
    save_frame(current)
```

The current grid is never included among the choices. Every mutation changes at least one pixel, so each iteration after initialization must move to a different frame. This does not guarantee actual visual improvement. The generator never uses the reference circle, geometry scores, or a target-specific drawing function.

`jev_pick` makes one `client.system_one` call containing one `Choice` question. Put the prompt, ASCII legend, and candidate grids in `state`; use neutral IDs as the possible answers. Select the original grid identified by the returned choice. Keep row boundaries and question wording fixed. [Choice API](https://docs.typesafe.ai/primitives/choice)

Keep the existing outputs: Markdown frames, final text and SVG, per-step candidate/decision logs, and a run manifest. Record the generator version, schedule, changed-pixel counts, actual model, token usage, and latency. Flush completed frames as the run progresses and rely on SDK retries for transient failures. Load `TYPESAFE_API_KEY` from the project's Git-ignored `.env`.

Validate in this order:

- Check that initial 4×4 blocks are uniform, all pixels stay binary, mutations affect one bounded square, and parent grids are unchanged. Verify that no candidate equals the current frame, then check the phase boundaries and existing selection/output/failure behavior.
- Run the standalone corruption diagnostic on three nested noise layouts: 0, 1, 4, 16, 40, 80, and 160 flipped pixels. Compare every adjacent pair in both orders (36 calls) and report the results by corruption level. Do not expose the labels to Jev or use them in generation.
- Run the same 500-step search with several seeds and a random selector baseline, then inspect progress and final frames alongside the earlier noisy run. Report image quality separately from successful API execution.

These changes preserve the random-generator-plus-Jev experiment. They add no learned model, annealing, population search, concurrency within a run, or UI. A successful run can still fail to produce the requested shape; keep the artifacts and report that outcome honestly.
