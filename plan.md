Jiffusion: current design
=========================

Goal: a diffusion-shaped loop where Jev supplies all the judgment. Code owns proposals, policy, and the reveal; Jev only answers typed questions about grids.

Loop (pseudocode):

```python
noise = noise_grid(size, rng)                       # x_T, fixed for the run
x0 = best_by_score(blobs_from(noise) + compositions())
for step, extent in enumerate(schedule(steps, size)):
    candidates = [propose(x0, extent, rng) for _ in range(8)]   # strokes / transforms / denoise ops
    scores = jev_score(prompt, [x0] + candidates)               # one request, one Score per grid
    best = argmax(candidates, scores)
    if scores[best] > scores[x0] + margin and jev_pick(prompt, [x0, best]) == best:
        x0 = best                                               # two independent judgments agree
    frame = blend(noise, x0, alpha(step))                       # what the viewer sees
    if no accepted edit for `patience` steps: break
```

Design decisions and the evidence behind them (details in validation.md):

1. **Edits must be perceivable.** Jev's choices are content-consistent for edits with a ≥4 px footprint and collapse to position bias below that. The stroke schedule never goes under `MIN_EXTENT = 4`.
2. **Show the current frame; make keeping the default.** A bare "which is best" Choice always moves and drifted into blobs. Absolute Scores with a margin, plus a head-to-head confirmation, accept only real improvements. About half of Score-approved edits are vetoed by the head-to-head, so both judgments matter.
3. **Search in x₀ space, display in x_t space.** Judging blended noisy frames is unreliable early; judging clean estimates is where Jev is strong. The reveal is derived from the estimate, like a sampler blending toward its x₀ prediction.
4. **Noise still matters.** Half the first-round candidates are read out of the noise, so different seeds start from different blobs and end at different pictures.
5. **Generic proposals only.** Ellipse, ring, rectangle, line, stretch, shift, and local denoise operators. No prompt-specific templates.

Open problems: compositional prompts (duck) stall around Score 2.0 ("probably the subject"); random single strokes rarely propose the right arrangement of parts. Candidates for the next iteration: a larger first-round tournament, Jev-directed edit regions, or per-part Noul questions.
