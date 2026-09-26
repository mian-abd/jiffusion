import { LEVELS, fromAscii } from './frame.js'

// Encode a frame sequence as code blocks (the "video as code" format).
export function encodeVideo(frames, { rle = false, prompt = '' } = {}) {
  const head = [
    `# jiffusion video · ${frames.length} frames · ${frames[0].w}x${frames[0].h}`,
    prompt ? `# prompt: ${prompt}` : '',
    `# levels: ${LEVELS.join(' ')} (space ░ ▒ ▓ █)`,
    `# encoding: ${rle ? 'run-length "count+char"' : 'raw'}`,
  ].filter(Boolean)
  const body = []
  frames.forEach((f, i) => {
    body.push(`[frame ${i}]`)
    for (let y = 0; y < f.h; y++) {
      let row = ''
      for (let x = 0; x < f.w; x++) row += LEVELS[f.data[y * f.w + x]]
      body.push(rle ? rleRow(row) : row)
    }
  })
  return [...head, ...body].join('\n')
}

function rleRow(row) {
  let out = ''
  let last = row[0]
  let n = 1
  for (let i = 1; i <= row.length; i++) {
    if (i < row.length && row[i] === last) {
      n++
    } else {
      out += n + last
      if (i < row.length) {
        last = row[i]
        n = 1
      }
    }
  }
  return out
}

// Accepts a "string of images": a JSON array of {rows:[...]} / {ascii:"..."}
// objects, plain ASCII blocks separated by blank lines, or the jiffusion
// code-block format (header lines + [frame N] markers).
export function parseImages(str) {
  const s = str.trim()
  if (!s) throw new Error('Paste a string of images first.')
  if (s.startsWith('[') || s.startsWith('{')) {
    const arr = JSON.parse(s)
    const list = Array.isArray(arr) ? arr : [arr]
    return list.map((it) => fromAscii((it.rows || [it.ascii]).join('\n')))
  }
  // Code-block format: frames delimited by [frame N] markers.
  if (/\[frame \d+\]/.test(s)) {
    const blocks = s
      .split(/\[frame \d+\]/)
      .slice(1)
      .map((b) => b.split('\n').filter((l) => !l.startsWith('#')).join('\n').trim())
      .filter(Boolean)
    if (blocks.length < 1) throw new Error('No frames found.')
    return blocks.map(fromAscii)
  }
  const blocks = s.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean)
  if (blocks.length < 2) throw new Error('Expected at least 2 images separated by blank lines.')
  return blocks.map(fromAscii)
}
