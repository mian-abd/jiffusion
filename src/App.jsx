import React, { useEffect, useMemo, useRef, useState } from 'react'
import { fromAscii } from './lib/frame.js'
import { encodeVideo } from './lib/video.js'

const POLL_MS = 400
const key = (k) => `c${String(k).padStart(3, '0')}`

// Jev's number for a candidate: Score's expected level (0..3) or Choice's probability.
function candidateScore(step, k) {
  const s = step.scores?.[key(k)]?.score
  if (s != null) return s
  const p = step.answer?.probabilities?.[key(k)]
  return p == null ? null : p * 3
}

// A frame rendered as monochrome ASCII, tinted by average intensity.
function FrameView({ text, size = 1, dim = false }) {
  const avg = useMemo(() => {
    const cells = text.replace(/\n/g, '')
    let sum = 0
    for (const ch of cells) sum += ' ░▒▓█'.indexOf(ch)
    return cells.length ? sum / cells.length / 4 : 0
  }, [text])
  const light = 22 + avg * 72
  return (
    <pre
      className={`frame${dim ? ' dim' : ''}`}
      style={{ color: `hsl(0,0%,${light}%)`, fontSize: `${size * 12}px`, lineHeight: '1em' }}
    >
      {text}
    </pre>
  )
}

// Pixel-perfect thumbnail: one filled rect per cell.
function Thumb({ text, px = 4, dim = false }) {
  const ref = useRef(null)
  const f = useMemo(() => fromAscii(text), [text])
  useEffect(() => {
    const ctx = ref.current.getContext('2d')
    ctx.fillStyle = '#050505'
    ctx.fillRect(0, 0, f.w * px, f.h * px)
    for (let y = 0; y < f.h; y++) {
      for (let x = 0; x < f.w; x++) {
        const v = f.data[y * f.w + x]
        ctx.fillStyle = `hsl(0,0%,${100 - v * 22}%)`
        ctx.fillRect(x * px, y * px, px, px)
      }
    }
  }, [f, px])
  return <canvas ref={ref} width={f.w * px} height={f.h * px} className={dim ? 'dim' : ''} />
}

function CodeBlock({ text }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch {}
  }
  return (
    <div className="codebox">
      <div className="codebar">
        <span>video · code blocks</span>
        <button onClick={copy}>{copied ? 'copied ✓' : 'copy'}</button>
      </div>
      <pre className="code">{text}</pre>
    </div>
  )
}

// ---- branch tree: every accepted decision as a row of the candidates Jev saw ----

const NW = 104
const NH = 118
const GX = 12
const GY = 44
const PITCH = NW + GX

function buildTree(noise, steps) {
  const root = { label: 'seed noise', kids: [], text: noise }
  let parent = root
  let prevWinCol = -1
  // Only steps where Jev accepted an edit change the picture; kept steps are skipped.
  steps.filter((st) => !st.kept && st.selected_index != null).forEach((st) => {
    const n = Math.min(8, st.candidates.length)
    const order = st.candidates.map((_, k) => k).slice(0, n)
    if (!order.includes(st.selected_index)) order[order.length - 1] = st.selected_index
    const winCol = prevWinCol < n / 2 ? Math.min(n - 2, 6) : 1
    const others = order.filter((k) => k !== st.selected_index).slice(0, n - 1)
    const slots = Array(n).fill(null)
    slots[winCol] = st.selected_index
    others.forEach((k, i) => {
      slots[i < winCol ? i : i + 1] = k
    })
    prevWinCol = winCol
    const nodes = slots.map((k) => ({
      k,
      text: st.candidates[k],
      score: candidateScore(st, k),
      win: k === st.selected_index,
      step: st.step,
      kind: st.edits?.[k]?.kind ?? 'start',
      kids: [],
    }))
    parent.kids = nodes
    parent = nodes[winCol]
  })
  return root
}

function place(node, cx, depth = 0) {
  node.x = cx - NW / 2
  node.y = depth * (NH + GY)
  node.depth = depth
  if (node.kids.length) {
    const row = node.kids.length * PITCH - GX
    let kx = cx - row / 2 + NW / 2
    node.kids.forEach((k) => {
      place(k, kx, depth + 1)
      kx += PITCH
    })
  }
}

function collect(node, out = []) {
  out.push(node)
  node.kids.forEach((k) => collect(k, out))
  return out
}

function TreeDiagram({ noise, steps }) {
  const [tx, setTx] = useState(8)
  const [ty, setTy] = useState(8)
  const [scale, setScale] = useState(1)
  const svgRef = useRef(null)
  const drag = useRef(null)

  const { nodes, edges, vbw, vbh } = useMemo(() => {
    const root = buildTree(noise, steps)
    place(root, (8 * PITCH - GX) / 2)
    const nodes = collect(root)
    const minX = Math.min(...nodes.map((n) => n.x))
    const off = minX < 8 ? 8 - minX : 0
    nodes.forEach((n, i) => {
      n.id = i
      n.x += off
    })
    const edges = nodes.flatMap((n) => n.kids.map((k) => ({ from: n, to: k })))
    const w = Math.max(...nodes.map((n) => n.x + NW)) + 8
    return { nodes, edges, vbw: w, vbh: Math.max(...nodes.map((n) => n.y)) + NH }
  }, [noise, steps])

  useEffect(() => {
    const box = svgRef.current?.parentElement
    if (!box) return
    const s = Math.min(1, (box.clientWidth - 16) / vbw, (box.clientHeight - 16) / vbh)
    setScale(s)
    setTx((box.clientWidth - vbw * s) / 2)
    setTy(8)
  }, [vbw, vbh])

  const onDown = (e) => {
    drag.current = { x: e.clientX, y: e.clientY, tx, ty }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onMove = (e) => {
    if (!drag.current) return
    setTx(drag.current.tx + e.clientX - drag.current.x)
    setTy(drag.current.ty + e.clientY - drag.current.y)
  }
  const onUp = () => (drag.current = null)
  const onWheel = (e) => {
    e.preventDefault()
    const rect = svgRef.current.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    const ns = Math.min(3, Math.max(0.2, scale * (e.deltaY > 0 ? 0.9 : 1.1)))
    setTx(mx - ((mx - tx) / scale) * ns)
    setTy(my - ((my - ty) / scale) * ns)
    setScale(ns)
  }

  return (
    <div className="treebox">
      <svg
        ref={svgRef}
        className="treecanv"
        width={vbw}
        height={vbh}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={onUp}
        onWheel={onWheel}
      >
        <g transform={`translate(${tx} ${ty}) scale(${scale})`}>
          {edges.map((e, i) => {
            const x1 = e.from.x + NW / 2
            const y1 = e.from.y + NH - 26
            const x2 = e.to.x + NW / 2
            const y2 = e.to.y
            const mid = y1 + GY / 2
            return (
              <path key={i} className={`edge${e.to.win ? ' hot' : ''}`} d={`M ${x1} ${y1} V ${mid} H ${x2} V ${y2}`} />
            )
          })}
          {nodes.map((n) => (
            <g key={n.id} className={`tnode${n.win ? ' win' : ''}`}>
              <foreignObject x={n.x} y={n.y} width={NW} height={NH - 26}>
                <div className="timg">
                  <Thumb text={n.text} px={3} />
                </div>
              </foreignObject>
              <text x={n.x + NW / 2} y={n.y + NH - 12} className="tscore">
                {n.depth === 0
                  ? 'noise'
                  : `${n.win ? '✓ ' : ''}${n.kind}${n.score != null ? ` ${n.score.toFixed(2)}` : ''}`}
              </text>
            </g>
          ))}
        </g>
      </svg>
      <div className="treehint">
        drag to pan · scroll to zoom · <b>✓</b> = the edit Jev accepted · kept steps hidden
      </div>
    </div>
  )
}

// ---- app ----

function verdict(step) {
  if (step.step === 1) return 'start'
  if (!step.kept) return `accepted ${step.edits?.[step.selected_index]?.kind ?? 'edit'}`
  if (step.confirmation) return 'vetoed by head-to-head'
  return 'kept'
}

async function api(path, options) {
  const res = await fetch(path, options)
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.error || `${res.status} ${res.statusText}`)
  return body
}

export default function App() {
  const [prompt, setPrompt] = useState('a circle')
  const [seed, setSeed] = useState(0)
  const [size, setSize] = useState(20)
  const [steps, setSteps] = useState(100)
  const [candidates, setCandidates] = useState(8)
  const [patience, setPatience] = useState(30)
  const [selector, setSelector] = useState('score')
  const [rle, setRle] = useState(false)
  const [running, setRunning] = useState(false)
  const [runId, setRunId] = useState(null)
  const [runState, setRunState] = useState(null) // { settings, steps[], noise, done, error }
  const [err, setErr] = useState('')
  const [shown, setShown] = useState(null) // step index to inspect; null = latest
  const timer = useRef(null)

  const start = async () => {
    setErr('')
    setRunState(null)
    setShown(null)
    setRunning(true)
    try {
      const res = await api('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, seed, size, steps, candidates, patience, selector }),
      })
      if (res.steps) { // serverless mode: the whole run comes back in one response
        setRunState({ settings: res.settings, steps: res.steps, noise: res.noise, done: true, error: res.error })
        setRunId(res.id)
        setRunning(false)
        if (res.error) setErr(res.error)
      } else {
        setRunId(res.id)
      }
    } catch (e) {
      setErr(e.message)
      setRunning(false)
    }
  }

  useEffect(() => {
    if (!runId || runId === 'vercel') return // 'vercel' runs arrive complete, nothing to poll
    let from = 0
    let acc = { settings: null, steps: [], noise: null, done: false, error: null }
    const tick = async () => {
      try {
        const page = await api(`/api/runs/${runId}?from=${from}`)
        if (page.error && !page.settings) throw new Error(page.error)
        acc = {
          settings: page.settings,
          steps: [...acc.steps, ...page.steps],
          noise: page.noise ?? acc.noise,
          done: page.done,
          error: page.error,
        }
        from = page.total ?? acc.steps.length
        setRunState(acc)
        if (page.done) {
          setRunning(false)
          if (page.error) setErr(page.error)
          return
        }
      } catch (e) {
        setErr(e.message)
        setRunning(false)
        return
      }
      timer.current = setTimeout(tick, POLL_MS)
    }
    tick()
    return () => clearTimeout(timer.current)
  }, [runId])

  const list = runState?.steps ?? []
  const latest = list[list.length - 1] ?? null
  const inspect = shown == null ? latest : list[Math.min(shown, list.length - 1)]
  const displayFrame = inspect ? inspect.frame : runState?.noise
  const scores = useMemo(() => list.map((s) => s.current_score).filter((v) => v != null), [list])

  const video = useMemo(() => {
    if (!runState?.done || !runState.noise || list.length === 0) return ''
    const frames = [runState.noise, ...list.map((s) => s.frame)].map(fromAscii)
    return encodeVideo(frames, { rle, prompt })
  }, [runState, list, rle, prompt])

  return (
    <div className="app">
      <header>
        <div className="logo">
          <span className="l1">jiffusion</span>
          <span className="l2">· noise → picture, steered by Jev</span>
        </div>
        {runState?.settings && (
          <div className="tabs">
            <span className="pill">{runState.settings.generator}</span>
            <span className="pill">{runState.settings.model ?? 'no model'}</span>
          </div>
        )}
      </header>

      <main>
        <section className="panel">
          <h2>generate</h2>
          <div className="row wrap">
            <input className="prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
            <label className="row">
              seed <input className="num" type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
            </label>
            <label className="row">
              size <input className="num" type="number" min={8} max={40} value={size} onChange={(e) => setSize(Number(e.target.value))} />
            </label>
            <label className="row">
              max steps <input className="num" type="number" min={1} max={500} value={steps} onChange={(e) => setSteps(Number(e.target.value))} />
            </label>
            <label className="row">
              candidates <input className="num" type="number" min={2} max={32} value={candidates} onChange={(e) => setCandidates(Number(e.target.value))} />
            </label>
            <label className="row">
              patience <input className="num" type="number" min={1} max={500} value={patience} onChange={(e) => setPatience(Number(e.target.value))} />
            </label>
            <label className="row">
              judge{' '}
              <select value={selector} onChange={(e) => setSelector(e.target.value)}>
                <option value="score">Jev · score + head-to-head</option>
                <option value="jev">Jev · single choice</option>
                <option value="random">random (no API)</option>
              </select>
            </label>
            <button className="primary" onClick={start} disabled={running || !prompt.trim()}>
              {running ? 'denoising…' : 'generate'}
            </button>
          </div>
          {err && <span className="err">{err}</span>}
        </section>

        {(runState || running) && (
          <section className="panel">
            <h2>
              {runState?.done
                ? `done · ${list.length} steps${runState.settings?.stop_reason ? ` · stopped on ${runState.settings.stop_reason}` : ''}`
                : latest
                  ? `step ${latest.step}/${runState?.settings?.steps ?? steps} · reveal ${(latest.alpha * 100).toFixed(0)}%`
                  : 'starting…'}
            </h2>
            <div className="stage">
              <div className="genframe">
                {displayFrame ? <FrameView text={displayFrame} size={1.6} /> : <span className="dim">waiting for noise…</span>}
              </div>
              {inspect && (
                <div className="side">
                  <div className="stephead">clean estimate x₀ (what Jev judges)</div>
                  <Thumb text={inspect.x0} px={6} />
                  <div className="stephead">
                    {verdict(inspect)}
                    {inspect.current_score != null && <> · score <b>{inspect.current_score.toFixed(2)}</b> / 3</>}
                  </div>
                  {scores.length > 1 && (
                    <div className="spark" title="Jev score of the current estimate over steps">
                      {scores.map((v, i) => (
                        <span key={i} style={{ height: `${Math.max(4, (v / 3) * 100)}%` }} />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
            {list.length > 0 && (
              <div className="row">
                <input
                  type="range"
                  min={0}
                  max={list.length - 1}
                  value={shown == null ? list.length - 1 : Math.min(shown, list.length - 1)}
                  onChange={(e) => setShown(Number(e.target.value))}
                  className="scrub"
                />
                <button className="small" onClick={() => setShown(null)} disabled={shown == null}>
                  follow latest
                </button>
              </div>
            )}
            {inspect && inspect.candidates && (
              <div className="stepdetail">
                <div className="stephead">
                  step {inspect.step} · {inspect.candidates.length} candidate edits · stroke extent {inspect.extent}
                </div>
                <div className="cands">
                  {inspect.candidates.map((c, k) => {
                    const s = candidateScore(inspect, k)
                    const win = k === inspect.selected_index
                    return (
                      <div className={`cand${win ? ' win' : ''}`} key={k}>
                        <Thumb text={c} px={3} dim={!win} />
                        <div className="fscore">
                          {inspect.edits?.[k]?.kind ?? 'start'}
                          {s != null ? ` · ${s.toFixed(2)}` : ''}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </section>
        )}
      </main>

      {runState?.noise && list.some((s) => !s.kept) && (
        <section className="treepanel">
          <div className="treelabel">branch tree · jev's path</div>
          <TreeDiagram noise={runState.noise} steps={list} />
        </section>
      )}

      <main>
        {video && (
          <section className="panel">
            <h2>video · code blocks</h2>
            <label className="row">
              <input type="checkbox" checked={rle} onChange={(e) => setRle(e.target.checked)} /> run-length encode
            </label>
            <CodeBlock text={video} />
          </section>
        )}
      </main>
    </div>
  )
}
