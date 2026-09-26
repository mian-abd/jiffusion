import React, { useMemo, useState } from 'react'
import { useEffect, useRef } from 'react'
import { mulberry32 } from './lib/rng.js'
import { randomFrame, copyFrame, applyFlip, toAscii } from './lib/frame.js'
import { STEPS, stepParams } from './lib/schedule.js'
import { mockJudge, realJudge } from './lib/judge.js'
import { encodeVideo } from './lib/video.js'

// A frame rendered as monochrome ASCII (terminal-green, tinted by intensity).
function FrameView({ f, size = 1, dim = false }) {
  let sum = 0
  for (let i = 0; i < f.data.length; i++) sum += f.data[i]
  const avg = sum / f.data.length / 4
  const light = 22 + avg * 72
  return (
    <pre
      className={`frame${dim ? ' dim' : ''}`}
      style={{ color: `hsl(0,0%,${light}%)`, fontSize: `${size * 12}px`, lineHeight: '1em' }}
    >
      {toAscii(f)}
    </pre>
  )
}

// Pixel-perfect thumbnail: one filled rect per cell, green intensity scale.
function Thumb({ f, px = 4, dim = false }) {
  const ref = useRef(null)
  useEffect(() => {
    const ctx = ref.current.getContext('2d')
    for (let y = 0; y < f.h; y++) {
      for (let x = 0; x < f.w; x++) {
        const v = f.data[y * f.w + x]
        ctx.fillStyle = v === 0 ? '#050505' : `hsl(0,0%,${14 + v * 17}%)`
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

const NW = 104 // node width (32px cells x ~3)
const NH = 118 // node height incl. label
const GX = 12
const GY = 44

function buildTree(gen) {
  const root = { label: 'seed noise', kids: [], seedFrame: gen.frames[0] }
  let parent = root
  let prevWinCol = -1 // column of the last picked node, -1 = first level
  gen.perStep.forEach((st) => {
    const order = st.cands.map((_, k) => k).slice(0, 8)
    if (!order.includes(st.chosen)) order[order.length - 1] = st.chosen
    // Re-slot candidates so the winner lands on the opposite side of the
    // previous pick — score-ranked fill keeps it deterministic but the path
    // alternates left/right instead of drifting one way.
    const winCol = prevWinCol < 4 ? 6 : 1 // alternate far side of the row
    const others = order.filter((k) => k !== st.chosen).slice(0, 7)
    const slots = Array(8).fill(null)
    slots[winCol] = st.chosen
    others.forEach((k, i) => {
      slots[i < winCol ? i : i + 1] = k
    })
    prevWinCol = winCol
    const nodes = slots.map((k) => ({
      k,
      frame: st.cands[k],
      score: st.scores[k],
      win: k === st.chosen,
      label: st.label,
      kids: [],
    }))
    parent.kids = nodes
    parent = nodes[winCol]
  })
  return root
}

// Tight row layout: each level's 8 candidates sit in a fixed-pitch row
// centered under the node that picked them — the pick zigzags left/right.
const PITCH = NW + GX // center-to-center distance between siblings

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

function TreeDiagram({ gen }) {
  const [tx, setTx] = useState(8)
  const [ty, setTy] = useState(8)
  const [scale, setScale] = useState(1)
  const svgRef = useRef(null)
  const drag = useRef(null)

  const { nodes, edges, vbw, vbh } = useMemo(() => {
    const root = buildTree(gen)
    const rootCx = (8 * PITCH - GX) / 2 // root centered over its kids' row
    place(root, rootCx)
    const nodes = collect(root)
    // Shift everything right so no node sits at negative x.
    const minX = Math.min(...nodes.map((n) => n.x))
    const off = minX < 8 ? 8 - minX : 0
    nodes.forEach((n, i) => {
      n.id = i
      n.x += off
    })
    const edges = nodes.flatMap((n) => n.kids.map((k) => ({ from: n, to: k })))
    const w = Math.max(...nodes.map((n) => n.x + NW)) + 8
    return { nodes, edges, vbw: w, vbh: Math.max(...nodes.map((n) => n.y)) + NH }
  }, [gen])
  // Fit the whole tree into view on first render.
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
    // keep the cursor's graph point fixed while zooming
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
              <path
                key={i}
                className={`edge${e.to.win ? ' hot' : ''}`}
                d={`M ${x1} ${y1} V ${mid} H ${x2} V ${y2}`}
              />
            )
          })}
          {nodes.map((n) => (
            <g key={n.id} className={`tnode${n.win ? ' win' : ''}`}>
              <foreignObject x={n.x} y={n.y} width={NW} height={NH - 26}>
                <div className="timg">
                  {n.seedFrame ? <Thumb f={n.seedFrame} px={3} /> : <Thumb f={n.frame} px={3} />}
                </div>
              </foreignObject>
              <text x={n.x + NW / 2} y={n.y + NH - 12} className="tscore">
                {n.seedFrame ? 'seed' : `${n.win ? '✓ ' : ''}${n.score.toFixed(2)}`}
              </text>
            </g>
          ))}
        </g>
      </svg>
      <div className="treehint">drag to pan · scroll to zoom · <b>hot</b> = jev's pick</div>
    </div>
  )
}


export default function App() {
  const [genPrompt, setGenPrompt] = useState('a dungeon corridor, torch light')
  const [seed, setSeed] = useState(1337)
  const [candPerStep, setCandPerStep] = useState(24)
  const [judge, setJudge] = useState('mock')
  const [rle, setRle] = useState(false)
  const [running, setRunning] = useState(false)
  const [gen, setGen] = useState(null) // { frames: chosen[], perStep: [{i, chosen, cands, scores}], done }
  const [genErr, setGenErr] = useState('')

  const runGenerate = async () => {
    setRunning(true)
    setGenErr('')
    setGen(null)
    const rng = mulberry32(seed)
    let cur = randomFrame(rng)
    const frames = [cur]
    const perStep = []
    try {
      for (let i = 0; i < STEPS.length; i++) {
        const { pct, max } = stepParams(i)
        const cands = Array.from({ length: candPerStep }, () => {
          const c = copyFrame(cur)
          applyFlip(c, rng, pct, max)
          return c
        })
        const scores =
          judge === 'real' ? await realJudge(genPrompt, cands) : mockJudge(genPrompt, cands, rng)
        let best = 0
        for (let k = 1; k < scores.length; k++) if (scores[k] > scores[best]) best = k
        cur = cands[best]
        frames.push(cur)
        perStep.push({ i, chosen: best, cands, scores })
        setGen({ frames: [...frames], perStep: [...perStep], done: false })
        await new Promise((r) => setTimeout(r, 260))
      }
      setGen({ frames, perStep, done: true })
    } catch (e) {
      setGenErr(e.message)
    } finally {
      setRunning(false)
    }
  }

  const genVideo = useMemo(
    () => (gen ? encodeVideo(gen.frames.slice(1), { rle, prompt: genPrompt }) : ''),
    [gen, rle, genPrompt],
  )

  const show = gen && gen.perStep.length > 0 ? gen.perStep[gen.perStep.length - 1] : null

  return (
    <div className="app">
      <header>
        <div className="logo">
          <span className="l1">jiffusion</span>
          <span className="l2">· jupscaler</span>
        </div>
      </header>

      <main>
        <section className="panel">
          <h2>jiffusion generate</h2>
          <div className="row wrap">
            <input
              className="prompt"
              value={genPrompt}
              onChange={(e) => setGenPrompt(e.target.value)}
            />
            <label className="row">
              seed{' '}
              <input
                className="num"
                type="number"
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value))}
              />
            </label>
            <label className="row">
              candidates/step{' '}
              <input
                className="num"
                type="number"
                min={4}
                max={1000}
                value={candPerStep}
                onChange={(e) => setCandPerStep(Math.min(1000, Math.max(4, Number(e.target.value))))}
              />
            </label>
            <label className="row">
              judge{' '}
              <select value={judge} onChange={(e) => setJudge(e.target.value)}>
                <option value="mock">mock (deterministic)</option>
                <option value="real">Jev API (needs VITE_JEV_API_KEY)</option>
              </select>
            </label>
            <label className="row">
              <input type="checkbox" checked={rle} onChange={(e) => setRle(e.target.checked)} />
              run-length encode
            </label>
            <button className="primary" onClick={runGenerate} disabled={running}>
              {running ? 'annealing…' : 'generate'}
            </button>
          </div>
          {genErr && <span className="err">{genErr}</span>}
        </section>

        {gen && (
          <>
            <section className="panel">
              <h2>
                {gen.done
                  ? 'final frame'
                  : `annealing · step ${gen.perStep.length}/${STEPS.length}`}
              </h2>
              <div className="genframe">
                <FrameView f={gen.frames[gen.frames.length - 1]} size={1.6} />
              </div>
              {show && (
                <div className="stepdetail">
                  <div className="stephead">
                    step {show.i} · {STEPS[show.i].label} · best of {show.cands.length}
                  </div>
                  <div className="cands">
                    {show.cands.slice(0, 8).map((c, k) => (
                      <div className={`cand${k === show.chosen ? ' win' : ''}`} key={k}>
                        <Thumb f={c} px={3} dim={k !== show.chosen} />
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
          </>
        )}
      </main>

      {gen && (
        <section className="treepanel">
          <div className="treelabel">branch tree · jev's path</div>
          <TreeDiagram gen={gen} />
        </section>
      )}

      <main>
        {gen && (
          <>
            {gen.done && (
              <section className="panel">
                <h2>video · code blocks</h2>
                <CodeBlock text={genVideo} />
              </section>
            )}
          </>
        )}
      </main>
    </div>
  )
}
