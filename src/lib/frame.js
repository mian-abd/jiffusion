// A frame is a grid of intensity levels 0..4.
// 0 = space, 1 = ░, 2 = ▒, 3 = ▓, 4 = █
export const LEVELS = [' ', '░', '▒', '▓', '█']
export const W = 48
export const H = 18

export function makeFrame(w = W, h = H) {
  return { w, h, data: new Uint8Array(w * h) }
}

export function randomFrame(rng, w = W, h = H) {
  const f = makeFrame(w, h)
  for (let i = 0; i < f.data.length; i++) f.data[i] = rng.int(0, 4)
  return f
}

export function copyFrame(f) {
  const g = makeFrame(f.w, f.h)
  g.data.set(f.data)
  return g
}

// Flip `pct` fraction of cells to a random level in 0..maxLevel.
export function applyFlip(f, rng, pct, maxLevel) {
  for (let i = 0; i < f.data.length; i++) {
    if (rng.float() < pct) f.data[i] = rng.int(0, maxLevel)
  }
}

export function toAscii(f) {
  const rows = []
  for (let y = 0; y < f.h; y++) {
    let row = ''
    for (let x = 0; x < f.w; x++) row += LEVELS[f.data[y * f.w + x]]
    rows.push(row)
  }
  return rows.join('\n')
}

export function fromAscii(str) {
  const rows = str.split('\n').map((r) => r.trimEnd()).filter((r) => r.length > 0)
  if (rows.length === 0) throw new Error('Empty image block')
  const w = rows[0].length
  const f = makeFrame(w, rows.length)
  for (let y = 0; y < rows.length; y++) {
    for (let x = 0; x < rows[y].length; x++) {
      const idx = LEVELS.indexOf(rows[y][x])
      f.data[y * w + x] = idx === -1 ? 0 : idx
    }
  }
  return f
}
