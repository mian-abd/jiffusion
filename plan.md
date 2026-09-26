Jiffusion: current experiment
============================

Keep one synchronous `for` loop: generate random candidates, ask Jev to select the closest visual match, and use that winner for the next iteration.

Defaults: a **20×20** output, **500 sequential iterations**, **16 new candidates** per iteration, prompt **“a circle”**, seed 0, and model `jev-1.13.0`. Each request contains only the current candidate set. The original idea remains in `rough_plan.md`; the changes below address the noisy initial results.

1. **Coarse initialization.** Each starting candidate is a random 5×5 binary grid enlarged to 20×20 with nearest-neighbor sampling. The initial choice is among broad regions rather than 400 independent pixels.
2. **Black and white.** Store pixel intensities as 0 or 4, rendering them as space or `█`. Test shape selection before restoring intermediate shades.
3. **Connected patch edits.** A mutation paints one randomly placed square uniformly black or white, choosing the opposite color from its top-left pixel to ensure something changes. Every candidate starts from a copy of the same current grid.
4. **Quickly reduce edit size.** At 500 iterations, step 1 initializes, steps 2–50 edit 4×4 squares, steps 51–200 edit 2×2 squares, and steps 201–500 flip one pixel. This spends most iterations making edits smaller than the old 40-pixel minimum.
5. **Check incremental judgment.** Independently compare a reference circle at increasing corruption levels, reversing the candidate order. This tests whether Jev recognizes small improvements; knowing the names of clean shapes alone is insufficient.

The core loop stays simple (pseudocode):

```python
current = None
for patch_size in schedule(500):
    candidates = [
        random_grid(20, rng) if current is None
        else mutate(current, patch_size, rng)
        for _ in range(16)
    ]
    rng.shuffle(candidates)
    current = jev_pick(prompt, candidates)
    save_frame(current)
```

The current grid is never included among the choices. Every mutation changes at least one pixel, so each iteration after initialization must move to a different frame. This does not guarantee actual visual improvement. The generator never uses the reference circle, geometry scores, or a target-specific drawing function.

`jev_pick` makes one `client.system_one` call containing one `Choice` question. Put the prompt, pixel legend, and candidate grids in `state`; use neutral IDs as the possible answers. Select the original grid identified by the returned choice. Preserve whitespace and keep question wording fixed. [Choice API](https://docs.typesafe.ai/primitives/choice)

Keep the existing outputs: Markdown frames, final text and SVG, per-step candidate/decision logs, and a run manifest. Record the generator version, schedule, changed-pixel counts, actual model, token usage, and latency. Flush completed frames as the run progresses and rely on SDK retries for transient failures. Load `TYPESAFE_API_KEY` from the project's Git-ignored `.env`.

Validate in this order:

- Check that initial 4×4 blocks are uniform, all pixels stay binary, mutations affect one bounded square, and parent grids are unchanged. Verify that no candidate equals the current frame, then check the phase boundaries and existing selection/output/failure behavior.
- Run the standalone corruption diagnostic on three nested noise layouts: 0, 1, 4, 16, 40, 80, and 160 flipped pixels. Compare every adjacent pair in both orders (36 calls) and report the results by corruption level. Do not expose the labels to Jev or use them in generation.
- Run the same 500-step search with several seeds and a random selector baseline, then inspect progress and final frames alongside the earlier noisy run. Report image quality separately from successful API execution.

These changes preserve the random-generator-plus-Jev experiment. They add no learned model, annealing, population search, concurrency within a run, or UI. A successful run can still fail to produce the requested shape; keep the artifacts and report that outcome honestly.
