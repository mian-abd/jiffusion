// Deterministic PRNG (mulberry32) so runs are replayable by seed.
export function mulberry32(seed) {
  let a = (seed >>> 0) || 1
  const float = () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
  return {
    float,
    int(min, max) {
      return Math.floor(float() * (max - min + 1)) + min
    },
  }
}

export function hashStr(s) {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}
