# Jiffusion — demo script

**JEVATHON · TypeSafe AI × The AI Collective · San Francisco · September 26, 2026**
Target length: 4 minutes talk + 1 minute Q&A. One laptop, two terminals already running (`npm run api`, `npm run dev`), browser on `http://localhost:5173`, a finished "a circle" run open in a second tab as a fallback.

---

## 0. Before you walk up (checklist)

- [ ] `.env` has `TYPESAFE_API_KEY`; `curl localhost:8787/api/health` returns `"key": true`
- [ ] Prompt box pre-filled with `a circle`, seed `0`, size `20`, patience `30`
- [ ] Fallback tab: `runs/v8-circle-s0` rendered (`docs/v8-circle.png`) in case Wi-Fi dies
- [ ] `check_decisions.py` output in a terminal, scrolled to the summary line
- [ ] Timer visible

---

## 1. Hook — 20 s

> "Every image model you've used is a neural network that learned to denoise.
> We built one with **no neural network for the image at all**. The only intelligence in the loop is Jev answering typed questions.
> This is Jiffusion: Jev, plus gif, plus diffusion."

*Click **generate**. Let the noise sit on screen while you talk. Do not narrate the frames yet.*

---

## 2. What you're seeing — 45 s

*Point at the left pane (noise fading in) and the right pane (clean estimate + score).*

> "On the left: pure grayscale noise, different for every seed, fading into a picture. That's the viewer.
> On the right: the clean estimate Jev is actually judging, and Jev's score for it, zero to three.
>
> Every step, plain code proposes eight random edits — an ellipse, a rectangle, a line, a stretch, an erase. No template for a circle anywhere in the code; the same generator draws a duck.
> Jev **scores all nine grids in one request**, in about 200 milliseconds. Code applies the policy: the best edit has to beat the current picture by a margin, and then win a **second, independent head-to-head Choice** against it. Two agreeing judgments, or nothing changes."

*When an edit is accepted, the right pane says "accepted ellipse"; when vetoed, "vetoed by head-to-head". Call one out live if it happens.*

---

## 3. The engineering story (why this is a Jev demo, not an AI-score demo) — 60 s

*Switch to the terminal with `check_decisions.py` output.*

> "We didn't start here. The first version asked Jev one question — 'which of these 16 grids looks most like a circle' — 500 times. It produced noise. 2.4 million tokens of noise.
>
> So we measured Jev instead of guessing. Same eight candidates, shuffled five ways.
> Result: when edits are at least four pixels wide, Jev picks the **same grid 80% of the time** — chance is 12%. Below that, it collapses to position bias. And a bare 'which is best' question always moves, so good frames drift into blobs.
>
> Three fixes, each backed by a diagnostic:
> 1. **Edits Jev can see** — strokes never shrink below four pixels.
> 2. **Absolute Score plus a margin** — keeping the picture is the default, not a competing option.
> 3. **Head-to-head confirmation** — half of the edits the Score approves get vetoed by the Choice. Two calibrated judgments beat one.
>
> Circles now converge in 33 to 75 steps, under 200k tokens, and the run **stops itself on plateau**. That's the difference between decorating a pipeline with an AI score and making Jev's probability distribution the control plane."

---

## 4. The business — 60 s

*Switch back to the browser; the run should be finished or close.*

> "Why does this matter beyond pixel art?
>
> **Jev is a cheap, fast, calibrated judge.** Sub-second, typed, with a probability you can threshold. That makes any generate-then-judge loop viable at a price where you can afford to ask on every iteration, not just at the end.
>
> Jiffusion is the toy version of a pattern we think is a product:
> - **Guided search where the generator is dumb and the judge is smart.** Marketing variants, UI layouts, level design, molecule or schedule candidates — anywhere you can enumerate options but can't write the objective function.
> - **A verification layer for other generative models.** The Score + head-to-head gate we built is model-agnostic: put it in front of a diffusion model, an LLM writing copy, or an agent's next action, and only accept outputs two independent Jev judgments agree improved things.
> - **Auditability by default.** Every candidate, score, confidence and veto is logged. You can replay a run under a different threshold without calling the model again — compliance teams love that.
>
> Cost math from today: a full run is under a dollar of tokens and about a minute. The judging design transfers unchanged."

---

## 5. Honest limits + what's next — 30 s

*Show `docs/v8-duck.png`.*

> "Compositional prompts are the open problem. 'A duck' gets us bird-like silhouettes Jev rates 'probably the subject', not a duck. The judge is fine — the random proposer rarely offers the right arrangement of parts.
> Next: a bigger first-round tournament, Jev choosing *where* to edit, and per-part yes/no questions — 'is there a beak?' — summed into the score. All of it is more Jev questions, not a new model."

---

## 6. Close — 15 s

> "Noise in, picture out, and every decision along the way is a typed answer from Jev you can inspect.
> Thanks to TypeSafe AI and The AI Collective for hosting, CodeRabbit for co-hosting, and HackerSquad for running submissions. Repo's public — `github.com/mian-abd/jiffusion`. Questions?"

---

## Q&A — likely questions and short answers

**"Isn't the circle just an ellipse primitive? That's cheating."**
The primitive set is generic (ellipse, ring, rect, line, stretch, shift, denoise ops) and identical for every prompt. The interesting part isn't the ellipse; it's that Jev *rejects* the other 7 proposals plus the oversize/blob variants, and that the same loop from noise produces different circles per seed.

**"Why Score and Choice? Why not one?"**
They fail differently. Score gives an absolute gradient and a keep-by-default policy but re-scores the same frame ±0.15. Choice is sharpest head-to-head but position-biased among many lookalikes. Requiring both cut accepted-but-bad edits roughly in half.

**"Token cost per step?"**
~3k input tokens for 9 grids of 20×20 in one request; ~200 ms. A 60-step run is ~200k tokens.

**"Why grayscale noise if Jev judges the clean estimate?"**
Two reasons: the reveal is what a sampler actually does — blend toward its x₀ prediction — and half the starting candidates are read *out of* the noise, so the seed genuinely changes the picture.

**"Does this generalize to real images?"**
The judging gate does. The proposer is the weak link and would be replaced by a real generative model; Jev stays as the accept/veto/stop policy.

**"How do you know Jev isn't just picking position 0?"**
`check_decisions.py`: same set, five shuffles, 80% grid agreement vs 20–40% position agreement. It's in the repo.

---

## Tailoring notes for this panel

Judges include people from **Cognition**, **Anthropic**, **xAI**, **Scout**, **Revamp**, **CodeRabbit**, **Lobster Capital**, **Leading Edge VC**, **Photon**, and **Women in AI Club**.

- Agent / infra folks (Cognition, Anthropic, xAI, CodeRabbit): lean on section 3 — the two-judgment accept gate and plateau stop are an **agent action policy** in disguise. Mention that `steps.jsonl` is a replayable decision ledger.
- Investors (Lobster, Leading Edge): lean on section 4 — cheap calibrated judgment makes generate-and-check loops economically viable per iteration; the moat is the judging design + logs, not the toy generator.
- Product / commerce (Scout, Revamp, Photon): the "guided search where the generator is dumb" line — variant selection, layout, catalog imagery — is the concrete use case.

Keep the duck slide. Judges reward an honest limit more than a hidden one.
