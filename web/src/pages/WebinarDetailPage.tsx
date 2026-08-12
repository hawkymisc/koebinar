import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import {
  fetchVideoObjectUrl,
  getWebinar,
  patchScript,
  patchPublication,
  runStep,
} from '../api/endpoints'
import { PIPELINE_STEPS, type ScriptSlide, type Webinar } from '../api/types'
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
  const [updatingPublication, setUpdatingPublication] = useState(false)
  const [copied, setCopied] = useState(false)

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

  async function handlePublication(published: boolean) {
    if (!id) return
    setUpdatingPublication(true)
    try {
      const updated = await patchPublication(id, published)
      setWebinar(updated)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '公開状態を変更できませんでした')
    } finally {
      setUpdatingPublication(false)
    }
  }

  async function copyViewerUrl() {
    if (!id) return
    await navigator.clipboard.writeText(`${window.location.origin}/watch/${id}`)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1800)
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

      {webinar.status === 'completed' && (
        <section className={`card publication-card ${webinar.published_at ? 'is-published' : ''}`}>
          <div>
            <p className="publication-kicker">視聴者ページ</p>
            <h3>{webinar.published_at ? '公開中です' : '視聴者への公開準備ができました'}</h3>
            <p className="muted">
              {webinar.published_at
                ? 'このURLを知っている人は、動画の視聴と資料に基づく質問ができます。'
                : '公開すると、APIトークンを表示しない専用の視聴ページが有効になります。'}
            </p>
          </div>
          {webinar.published_at ? (
            <div className="publication-actions">
              <a className="btn btn-primary" href={`/watch/${webinar.id}`} target="_blank" rel="noreferrer">
                視聴者ページを開く
              </a>
              <button className="btn" type="button" onClick={() => void copyViewerUrl()}>
                {copied ? 'コピーしました' : 'URLをコピー'}
              </button>
              <button
                className="btn"
                type="button"
                disabled={updatingPublication}
                onClick={() => void handlePublication(false)}
              >
                公開を停止
              </button>
            </div>
          ) : (
            <button
              className="btn btn-primary"
              type="button"
              disabled={updatingPublication}
              onClick={() => void handlePublication(true)}
            >
              {updatingPublication ? '公開中…' : '視聴者に公開する'}
            </button>
          )}
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

    </div>
  )
}
