import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import {
  createQuestion,
  fetchVideoObjectUrl,
  getQuestion,
  getWebinar,
  patchScript,
  runStep,
} from '../api/endpoints'
import { PIPELINE_STEPS, type Question, type ScriptSlide, type Webinar } from '../api/types'
import { StatusBadge } from '../components/StatusBadge'

const IN_FLIGHT_STATUSES = new Set(['queued', 'running'])
const POLL_INTERVAL_MS = 2000

export function WebinarDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [webinar, setWebinar] = useState<Webinar | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [slides, setSlides] = useState<ScriptSlide[]>([])
  const [savingScript, setSavingScript] = useState(false)
  const [runningStep, setRunningStep] = useState<string | null>(null)
  const [videoUrl, setVideoUrl] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!id) return
    try {
      const w = await getWebinar(id)
      setWebinar(w)
      setSlides(w.script?.slides ?? [])
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ウェビナーの取得に失敗しました')
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!webinar || !IN_FLIGHT_STATUSES.has(webinar.status)) return
    const timer = setInterval(() => void load(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [webinar, load])

  useEffect(() => {
    if (webinar?.status !== 'completed' || !id) return
    let revoke: string | null = null
    void fetchVideoObjectUrl(id).then((url) => {
      revoke = url
      setVideoUrl(url)
    })
    return () => {
      if (revoke) URL.revokeObjectURL(revoke)
    }
  }, [webinar?.status, id])

  async function handleSaveScript() {
    if (!id) return
    setSavingScript(true)
    try {
      const w = await patchScript(id, slides)
      setWebinar(w)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '台本の保存に失敗しました')
    } finally {
      setSavingScript(false)
    }
  }

  async function handleRunStep(step: string) {
    if (!id) return
    setRunningStep(step)
    try {
      const w = await runStep(id, step)
      setWebinar(w)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `ステップ ${step} の再実行に失敗しました`)
    } finally {
      setRunningStep(null)
    }
  }

  if (error && !webinar) {
    return <p className="error-box">{error}</p>
  }
  if (!webinar) {
    return <p className="muted">読み込み中…</p>
  }

  return (
    <div>
      <section className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2>{webinar.theme}</h2>
          <StatusBadge status={webinar.status} />
        </div>
        <p className="muted">
          {webinar.lang.toUpperCase()} / {webinar.template} / {webinar.style} / {webinar.duration_min}分
          {webinar.current_step ? ` / 現在のステップ: ${webinar.current_step}` : ''}
        </p>
        {webinar.error && <p className="error-box">{webinar.error}</p>}
        {error && <p className="error-box">{error}</p>}

        <h3>ステップ再実行</h3>
        <div className="step-list">
          {PIPELINE_STEPS.map((step) => (
            <button
              key={step}
              className="btn btn-sm"
              disabled={runningStep !== null || IN_FLIGHT_STATUSES.has(webinar.status)}
              onClick={() => void handleRunStep(step)}
            >
              {runningStep === step ? '実行中…' : step}
            </button>
          ))}
        </div>
      </section>

      {videoUrl && (
        <section className="card">
          <h3>生成された動画</h3>
          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <video className="player" src={videoUrl} controls />
        </section>
      )}

      <section className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h3>台本</h3>
          <button
            className="btn btn-primary btn-sm"
            disabled={savingScript || slides.length === 0}
            onClick={() => void handleSaveScript()}
          >
            {savingScript ? '保存中…' : '保存して再生成'}
          </button>
        </div>
        {slides.length === 0 ? (
          <p className="muted">台本はまだ生成されていません。</p>
        ) : (
          <div className="slide-editor">
            {slides.map((slide, i) => (
              <div className="slide" key={i}>
                <strong>
                  {i + 1}. {slide.title ?? `スライド ${i + 1}`}
                </strong>
                <textarea
                  value={(slide.narration as string) ?? ''}
                  onChange={(e) => {
                    const next = [...slides]
                    next[i] = { ...slide, narration: e.target.value }
                    setSlides(next)
                  }}
                />
              </div>
            ))}
          </div>
        )}
      </section>

      <QaWidget webinarId={webinar.id} />
    </div>
  )
}

function QaWidget({ webinarId }: { webinarId: string }) {
  const [message, setMessage] = useState('')
  const [questions, setQuestions] = useState<Question[]>([])
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollers = useRef(new Set<string>())

  function pollUntilAnswered(questionId: string) {
    if (pollers.current.has(questionId)) return
    pollers.current.add(questionId)
    const timer = setInterval(async () => {
      try {
        const q = await getQuestion(questionId)
        setQuestions((prev) => prev.map((p) => (p.id === q.id ? q : p)))
        if (q.status !== 'pending') {
          clearInterval(timer)
          pollers.current.delete(questionId)
        }
      } catch (err) {
        console.error('[QaWidget] polling answer failed:', err)
        clearInterval(timer)
        pollers.current.delete(questionId)
        setError(err instanceof ApiError ? err.message : '回答の取得に失敗しました')
      }
    }, POLL_INTERVAL_MS)
  }

  async function handleAsk(e: React.FormEvent) {
    e.preventDefault()
    if (!message.trim()) return
    setSending(true)
    setError(null)
    try {
      const q = await createQuestion(webinarId, message)
      setQuestions((prev) => [q, ...prev])
      setMessage('')
      if (q.status === 'pending') pollUntilAnswered(q.id)
    } catch (err) {
      console.error('[QaWidget] question submit failed:', err)
      setError(err instanceof ApiError ? err.message : '質問の送信に失敗しました')
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="card">
      <h3>視聴者Q&amp;A</h3>
      {error && <p className="error-box">{error}</p>}
      <form onSubmit={handleAsk} className="row">
        <input
          style={{ flex: 1 }}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="資料の内容について質問する"
        />
        <button className="btn btn-primary" type="submit" disabled={sending}>
          質問する
        </button>
      </form>
      <div className="qa-thread" style={{ marginTop: 12 }}>
        {questions.map((q) => (
          <div className="qa-item" key={q.id}>
            <p>
              <strong>Q.</strong> {q.message}
            </p>
            {q.status === 'pending' && <p className="muted">回答を生成中…</p>}
            {q.answer && (
              <p>
                <strong>A.</strong> {q.answer.text}
                <span className="muted"> (confidence: {q.answer.confidence.toFixed(2)})</span>
              </p>
            )}
            {q.status === 'held' && !q.answer && (
              <p className="muted">根拠が不十分なため回答を保留しています。</p>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
