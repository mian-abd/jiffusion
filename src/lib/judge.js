import { toAscii } from './frame.js'
import { hashStr } from './rng.js'

const clamp01 = (x) => Math.min(1, Math.max(0, x))

// Structure score: fraction of cells close to their neighbors' mean.
// Annealed frames get smoother, so "best" picks drive convergence.
function scoreFrame(f) {
  let good = 0
  let total = 0
  for (let y = 0; y < f.h; y++) {
    for (let x = 0; x < f.w; x++) {
      const v = f.data[y * f.w + x]
      const nb = []
      if (x > 0) nb.push(f.data[y * f.w + x - 1])
      if (x < f.w - 1) nb.push(f.data[y * f.w + x + 1])
      if (y > 0) nb.push(f.data[(y - 1) * f.w + x])
      if (y < f.h - 1) nb.push(f.data[(y + 1) * f.w + x])
      const m = nb.reduce((a, b) => a + b, 0) / nb.length
      total++
      if (Math.abs(v - m) <= 1) good++
    }
  }
  return good / total
}

// Mock judge: prompt-seeded, deterministic per (prompt, seed, candidate).
export function mockJudge(prompt, candidates, rng) {
  const h = hashStr(prompt)
  return candidates.map((f) => clamp01(scoreFrame(f) * 0.8 + rng.float() * 0.2 + (h % 7) / 100))
}

// Real Jev adapter (stub). One `choice` question per round; tournament
// rounds because a Choice caps at 255 options (1000 candidates → 4 rounds).
const JEV_URL = 'https://api.typesafe.ai/v1/jev'
const CAP = 255

export async function realJudge(prompt, candidates) {
  const key = import.meta.env.VITE_JEV_API_KEY
  if (!key) {
    throw new Error('VITE_JEV_API_KEY not set — real Jev judge unavailable. Switch judge to "mock".')
  }
  let pool = candidates.map((_, i) => i)
  while (pool.length > 1) {
    const next = []
    for (let i = 0; i < pool.length; i += CAP) {
      const batch = pool.slice(i, i + CAP)
      const res = await fetch(JEV_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${key}` },
        body: JSON.stringify({
          model: 'jev-latest',
          state: { prompt, candidates: batch.map((i) => toAscii(candidates[i])) },
          questions: {
            best: {
              type: 'choice',
              instructions: 'Which candidate frame best realizes the prompt?',
              criteria: Object.fromEntries(batch.map((_, j) => [`c${j}`, `frame ${j}`])),
            },
          },
        }),
      })
      const j = await res.json()
      const pick = j.answers.best.choice // e.g. "c3"
      next.push(batch[Number(pick.slice(1))])
    }
    pool = next
  }
  const win = pool[0]
  return candidates.map((_, i) => (i === win ? 1 : 0.9 - 0.8 * (i / (candidates.length - 1 || 1))))
}
