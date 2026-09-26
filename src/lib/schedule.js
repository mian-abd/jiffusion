// The 12-step anneal schedule. pct = fraction of cells flipped,
// max = highest intensity level a flipped cell may take.
// Cosine temperature modulates pct so early steps explore more,
// late steps settle (simulated-annealing style decay).
export const STEPS = [
  { pct: 0.8, max: 4, label: 'flip 80% · any level' },
  { pct: 0.7, max: 4, label: 'flip 70% · any level' },
  { pct: 0.6, max: 3, label: 'flip 60% · ≤ L3' },
  { pct: 0.5, max: 2, label: 'flip 50% · ≤ L2' },
  { pct: 0.4, max: 2, label: 'flip 40% · ≤ L2' },
  { pct: 0.4, max: 1, label: 'flip 40% · ≤ L1' },
  { pct: 0.4, max: 1, label: 'flip 40% · ≤ L1' },
  { pct: 0.2, max: 1, label: 'flip 20% · ≤ L1' },
  { pct: 0.1, max: 1, label: 'flip 10% · ≤ L1' },
  { pct: 0.1, max: 1, label: 'flip 10% · ≤ L1' },
  { pct: 0.1, max: 1, label: 'flip 10% · ≤ L1' },
]

export function stepParams(i) {
  const t = 0.5 + 0.5 * Math.cos((Math.PI * i) / (STEPS.length - 1)) // 1 → 0
  return { pct: STEPS[i].pct * (0.7 + 0.6 * t), max: STEPS[i].max }
}
