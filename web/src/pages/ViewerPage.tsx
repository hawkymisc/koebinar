import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import {
  createPublicQuestion,
  getPublicQuestion,
  getPublicWebinar,
  publicVideoUrl,
} from '../api/endpoints'
import type { PublicWebinar, Question } from '../api/types'

const POLL_INTERVAL_MS = 2000

export function ViewerPage() {
  const { id } = useParams<{ id: string }>()
  const [webinar, setWebinar] = useState<PublicWebinar | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [questions, setQuestions] = useState<Question[]>([])
  const [sending, setSending] = useState(false)
  const [questionError, setQuestionError] = useState<string | null>(null)
  const pollers = useRef(new Map<string, number>())

  useEffect(() => {
    if (!id) return
    let active = true
    void getPublicWebinar(id)
      .then((result) => {
        if (active) setWebinar(result)
      })
      .catch((error) => {
        if (!active) return
        setLoadError(
          error instanceof ApiError && error.status === 404
            ? 'このウェビナーは公開されていないか、URLが正しくありません。'
            : 'ウェビナーを読み込めませんでした。時間をおいて再度お試しください。',
        )
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [id])

  useEffect(() => {
    const currentPollers = pollers.current
    return () => {
      currentPollers.forEach((timer) => window.clearInterval(timer))
      currentPollers.clear()
    }
  }, [])

  function pollUntilAnswered(questionId: string) {
    if (!id || pollers.current.has(questionId)) return
    const timer = window.setInterval(async () => {
      try {
        const question = await getPublicQuestion(id, questionId)
        setQuestions((current) =>
          current.map((item) => (item.id === question.id ? question : item)),
        )
        if (question.status !== 'pending') {
          window.clearInterval(timer)
          pollers.current.delete(questionId)
        }
      } catch (error) {
        window.clearInterval(timer)
        pollers.current.delete(questionId)
        setQuestionError(error instanceof ApiError ? error.message : '回答を取得できませんでした。')
      }
    }, POLL_INTERVAL_MS)
    pollers.current.set(questionId, timer)
  }

  async function handleAsk(event: React.FormEvent) {
    event.preventDefault()
    const questionText = message.trim()
    if (!id || !questionText) return
    setSending(true)
    setQuestionError(null)
    try {
      const question = await createPublicQuestion(id, questionText)
      setQuestions((current) => [question, ...current])
      setMessage('')
      if (question.status === 'pending') pollUntilAnswered(question.id)
    } catch (error) {
      setQuestionError(
        error instanceof ApiError ? error.message : '質問を送信できませんでした。',
      )
    } finally {
      setSending(false)
    }
  }

  if (loading) {
    return (
      <main className="viewer-state" aria-live="polite">
        <div className="viewer-loader" />
        <p>ウェビナーを準備しています…</p>
      </main>
    )
  }

  if (loadError || !webinar) {
    return (
      <main className="viewer-state">
        <span className="viewer-brand" aria-label="Koebinar">
          Koebinar<span>.</span>
        </span>
        <div className="viewer-empty-icon">!</div>
        <h1>視聴できません</h1>
        <p>{loadError}</p>
      </main>
    )
  }

  return (
    <div className={`viewer-page viewer-theme-${webinar.template}`}>
      <header className="viewer-header">
        <span className="viewer-brand" aria-label="Koebinar">
          Koebinar<span>.</span>
        </span>
        <span className="viewer-live-label"><i /> ON DEMAND</span>
      </header>

      <main className="viewer-content">
        <section className="viewer-intro">
          <p className="viewer-eyebrow">AI WEBINAR · {webinar.lang === 'ja' ? 'JAPANESE' : 'ENGLISH'}</p>
          <h1>{webinar.theme}</h1>
          <div className="viewer-meta">
            <span>{webinar.duration_min} MIN</span>
            <span>FOR {webinar.audience}</span>
          </div>
        </section>

        <div className="viewer-grid">
          <section className="viewer-video-panel" aria-label="ウェビナー動画">
            {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
            <video src={publicVideoUrl(webinar.id)} controls preload="metadata" playsInline />
            <div className="viewer-video-footer">
              <span>AI-generated webinar</span>
              <span>Koebinar</span>
            </div>
          </section>

          <aside className="viewer-qa-panel">
            <div className="viewer-qa-heading">
              <p className="viewer-eyebrow">ASK THE WEBINAR</p>
              <h2>気になったことを<br />その場で質問</h2>
              <p>回答はこのウェビナーに使用された資料だけを根拠に生成されます。</p>
            </div>

            <form className="viewer-question-form" onSubmit={handleAsk}>
              <label htmlFor="viewer-question">質問を入力</label>
              <textarea
                id="viewer-question"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                rows={3}
                maxLength={1000}
                placeholder="例：このサービスの導入条件を教えてください"
              />
              <button type="submit" disabled={sending || !message.trim()}>
                {sending ? '回答を考えています…' : 'AIに質問する'}
                <span aria-hidden="true">↗</span>
              </button>
            </form>

            {questionError && <p className="viewer-question-error">{questionError}</p>}

            <div className="viewer-qa-thread" aria-live="polite">
              {questions.map((question) => (
                <article className="viewer-qa-item" key={question.id}>
                  <p className="viewer-question"><span>YOU</span>{question.message}</p>
                  {question.status === 'pending' && (
                    <p className="viewer-answer viewer-answer-pending">回答を生成しています…</p>
                  )}
                  {question.status === 'failed' && (
                    <p className="viewer-answer viewer-answer-pending">
                      回答を生成できませんでした。時間をおいて再度お試しください。
                    </p>
                  )}
                  {question.answer && (
                    <div className="viewer-answer">
                      <span className="viewer-ai-label">KOEBINAR AI</span>
                      <p>{question.answer.text}</p>
                      {question.answer.citations.length > 0 && (
                        <div className="viewer-citations">
                          <strong>出典</strong>
                          {[...new Set(question.answer.citations.map(
                            (citation) => citation.source_title ?? citation.document_id,
                          ))].map((source) => <span key={source}>{source}</span>)}
                        </div>
                      )}
                      <small>確信度 {Math.round(question.answer.confidence * 100)}%</small>
                    </div>
                  )}
                </article>
              ))}
            </div>
          </aside>
        </div>
      </main>

      <footer className="viewer-footer">
        <span>POWERED BY KOEBINAR</span>
        <span>AIの回答は登録資料に基づきます</span>
      </footer>
    </div>
  )
}
