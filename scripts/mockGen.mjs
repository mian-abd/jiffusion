// Runs the real jiffusion generator loop (noise -> 12-step anneal ->
// N candidates/step -> mock judge picks best) and writes the full
// branch data to public/mock-run.json for the frontend to render.
//
// Usage: node scripts/mockGen.mjs [seed] [candidatesPerStep] [prompt]
import { mkdirSync, writeFileSync } from 'node:fs'
import { mulberry32 } from '../src/lib/rng.js'
import { randomFrame, copyFrame, applyFlip, toAscii } from '../src/lib/frame.js'
import { STEPS, stepParams } from '../src/lib/schedule.js'
import { mockJudge } from '../src/lib/judge.js'

const seed = Number(process.argv[2] ?? 1337)
const CANDS = Number(process.argv[3] ?? 24)
const prompt = process.argv[4] ?? 'a dungeon corridor, torch light'

const rng = mulberry32(seed)
let cur = randomFrame(rng)
const seedFrame = toAscii(cur)
const steps = []

for (let i = 0; i < STEPS.length; i++) {
  const { pct, max } = stepParams(i)
  const cands = []
  for (let k = 0; k < CANDS; k++) {
    const c = copyFrame(cur)
    applyFlip(c, rng, pct, max)
    cands.push(c)
  }
  const scores = mockJudge(prompt, cands, rng)
  let best = 0
  for (let k = 1; k < CANDS; k++) if (scores[k] > scores[best]) best = k
  steps.push({
    i,
    label: STEPS[i].label,
    chosen: best,
    scores: scores.map((s) => +s.toFixed(3)),
    cands: cands.map(toAscii),
  })
  cur = cands[best]
}

mkdirSync('public', { recursive: true })
writeFileSync(
  'public/mock-run.json',
  JSON.stringify({ prompt, seed, candidatesPerStep: CANDS, seedFrame, steps }),
)
console.log(`wrote public/mock-run.json · ${steps.length} steps · ${CANDS} candidates/step`)
