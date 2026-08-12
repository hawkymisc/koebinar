import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createWebinar, listWebinars } from '../api/endpoints'
import type { Lang, Style, Template, Webinar, WebinarCreateInput } from '../api/types'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError } from '../api/client'

const EMPTY_FORM: WebinarCreateInput = {
  theme: '',
  audience: 'general',
  duration_min: 5,
  lang: 'ja',
  template: 'tech',
  style: 'keynote',
  auto_run: true,
}

export function WebinarListPage() {
  const [webinars, setWebinars] = useState<Webinar[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<WebinarCreateInput>(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()

  async function refresh() {
    setLoading(true)
    try {
      setWebinars(await listWebinars())
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ウェビナー一覧の取得に失敗しました')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.theme.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      const created = await createWebinar(form)
      setForm(EMPTY_FORM)
      navigate(`/webinars/${created.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ウェビナーの作成に失敗しました')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <section className="card">
        <h2>新規ウェビナー作成</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-grid">
            <label className="field">
              テーマ
              <input
                required
                value={form.theme}
                onChange={(e) => setForm({ ...form, theme: e.target.value })}
                placeholder="例: 新製品の紹介"
              />
            </label>
            <label className="field">
              対象者
              <input
                value={form.audience}
                onChange={(e) => setForm({ ...form, audience: e.target.value })}
              />
            </label>
            <label className="field">
              尺（分）
              <input
                type="number"
                min={1}
                value={form.duration_min}
                onChange={(e) => setForm({ ...form, duration_min: Number(e.target.value) })}
              />
            </label>
            <label className="field">
              言語
              <select
                value={form.lang}
                onChange={(e) => setForm({ ...form, lang: e.target.value as Lang })}
              >
                <option value="ja">日本語</option>
                <option value="en">English</option>
              </select>
            </label>
            <label className="field">
              テンプレート
              <select
                value={form.template}
                onChange={(e) => setForm({ ...form, template: e.target.value as Template })}
              >
                <option value="tech">Tech</option>
                <option value="casual">Casual</option>
                <option value="formal">Formal</option>
              </select>
            </label>
            <label className="field">
              話法スタイル
              <select
                value={form.style}
                onChange={(e) => setForm({ ...form, style: e.target.value as Style })}
              >
                <option value="casual">Casual</option>
                <option value="keynote">Keynote</option>
                <option value="formal">Formal</option>
                <option value="humorous">Humorous</option>
              </select>
            </label>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <label className="row">
              <input
                type="checkbox"
                checked={form.auto_run}
                onChange={(e) => setForm({ ...form, auto_run: e.target.checked })}
              />
              作成後すぐに生成を開始する
            </label>
            <button className="btn btn-primary" type="submit" disabled={submitting}>
              {submitting ? '作成中…' : '作成'}
            </button>
          </div>
        </form>
      </section>

      {error && <p className="error-box">{error}</p>}

      <section>
        <h2>ウェビナー一覧</h2>
        {loading ? (
          <p className="muted">読み込み中…</p>
        ) : webinars.length === 0 ? (
          <p className="muted">まだウェビナーがありません。上のフォームから作成してください。</p>
        ) : (
          <ul className="webinar-list">
            {webinars.map((w) => (
              <li key={w.id}>
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <a href={`/webinars/${w.id}`} onClick={(e) => { e.preventDefault(); navigate(`/webinars/${w.id}`) }}>
                    {w.theme}
                  </a>
                  <StatusBadge status={w.status} />
                </div>
                <p className="muted">
                  {w.lang.toUpperCase()} / {w.template} / {w.duration_min}分 /{' '}
                  {new Date(w.created_at).toLocaleString('ja-JP')}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
