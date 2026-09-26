import React, { useEffect, useMemo, useRef, useState } from 'react'
import { fromAscii } from './lib/frame.js'
import { encodeVideo } from './lib/video.js'

const POLL_MS = 400

// A frame rendered as monochrome ASCII (terminal-green, tinted by intensity).
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
      style={{ color: `hsl(150,75%,${light}%)`, fontSize: `${size * 12}px`, lineHeight: '1em' }}
    >
      {text}
    </pre>
  )
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
      const { id } = await api('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, seed, size, steps, candidates, patience, selector }),
      })
      setRunId(id)
    } catch (e) {
      setErr(e.message)
      setRunning(false)
    }
  }

  useEffect(() => {
    if (!runId) return
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
                  <FrameView text={inspect.x0} size={0.8} />
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
                    const s = inspect.scores?.[`c${String(k).padStart(3, '0')}`]
                    const win = k === inspect.selected_index
                    return (
                      <div className={`cand${win ? ' win' : ''}`} key={k}>
                        <FrameView text={c} size={0.5} dim={!win} />
                        <div className="fscore">
                          {inspect.edits?.[k]?.kind ?? 'start'}
                          {s ? ` · ${s.score.toFixed(2)}` : ''}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </section>
        )}

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
