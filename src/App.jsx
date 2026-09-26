import React, { useMemo, useState } from 'react'
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
      style={{ color: `hsl(150,75%,${light}%)`, fontSize: `${size * 12}px`, lineHeight: '1em' }}
    >
      {toAscii(f)}
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
                        <FrameView f={c} size={0.5} dim={k !== show.chosen} />
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
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
