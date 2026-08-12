import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createDocument, createWebinar, listDocuments, listWebinars } from '../api/endpoints'
import type {
  KnowledgeDocument,
  Lang,
  Style,
  Template,
  Webinar,
  WebinarCreateInput,
} from '../api/types'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError } from '../api/client'
import { extractKnowledgeFile } from '../features/knowledge/fileExtraction'

const EMPTY_FORM: WebinarCreateInput = {
  theme: '',
  audience: 'general',
  duration_min: 5,
  lang: 'ja',
  template: 'tech',
  style: 'keynote',
  instructions: '',
  document_ids: [],
  auto_run: true,
}

export function WebinarListPage() {
  const [webinars, setWebinars] = useState<Webinar[]>([])
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<WebinarCreateInput>(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [textTitle, setTextTitle] = useState('')
  const [textContent, setTextContent] = useState('')
  const navigate = useNavigate()

  async function refresh() {
    setLoading(true)
    try {
      const [nextWebinars, nextDocuments] = await Promise.all([listWebinars(), listDocuments()])
      setWebinars(nextWebinars)
      setDocuments(nextDocuments)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ウェビナー一覧の取得に失敗しました')
    } finally {
      setLoading(false)
    }
  }

  async function handleFiles(files: FileList | File[]) {
    const selectedFiles = Array.from(files)
    if (selectedFiles.length === 0) return
    setUploading(true)
    setError(null)
    try {
      const created: KnowledgeDocument[] = []
      for (const file of selectedFiles) {
        const extracted = await extractKnowledgeFile(file)
        created.push(
          await createDocument({
            title: extracted.title,
            source_type: 'text',
            content: extracted.content,
            metadata: extracted.metadata,
          }),
        )
      }
      addDocuments(created)
    } catch (err) {
      setError(err instanceof Error ? err.message : '資料のアップロードに失敗しました')
    } finally {
      setUploading(false)
    }
  }

  function addDocuments(created: KnowledgeDocument[]) {
    setDocuments((current) => [...created, ...current])
    setForm((current) => ({
      ...current,
      document_ids: [
        ...new Set([...(current.document_ids ?? []), ...created.map((document) => document.id)]),
      ],
    }))
  }

  async function handleTextDocument() {
    const content = textContent.trim()
    if (!content) return
    const title = textTitle.trim() || '貼り付け資料'
    setUploading(true)
    setError(null)
    try {
      const created = await createDocument({
        title,
        source_type: 'text',
        content,
        metadata: { filename: title, original_format: 'text' },
      })
      addDocuments([created])
      setTextTitle('')
      setTextContent('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'テキスト資料の登録に失敗しました')
    } finally {
      setUploading(false)
    }
  }

  function toggleDocument(id: string, checked: boolean) {
    setForm((current) => ({
      ...current,
      document_ids: checked
        ? [...new Set([...(current.document_ids ?? []), id])]
        : (current.document_ids ?? []).filter((documentId) => documentId !== id),
    }))
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
          <fieldset className="knowledge-fieldset">
            <legend>資料</legend>
            <label
              className="drop-zone"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault()
                void handleFiles(event.dataTransfer.files)
              }}
            >
              <input
                type="file"
                aria-label="資料ファイル"
                multiple
                accept=".txt,.md,.pdf,.pptx"
                disabled={uploading}
                onChange={(event) => {
                  if (event.target.files) void handleFiles(event.target.files)
                  event.target.value = ''
                }}
              />
              <span>{uploading ? '抽出・登録中…' : 'PDF / PPTX / TXT / MD を選択またはドロップ'}</span>
              <small>内容はブラウザ内で抽出し、プレーンテキストだけを登録します（最大20MB）</small>
            </label>
            <details className="text-ingest">
              <summary>テキストを直接貼り付ける</summary>
              <div className="text-ingest-fields">
                <label className="field">
                  資料名
                  <input
                    value={textTitle}
                    onChange={(event) => setTextTitle(event.target.value)}
                    placeholder="例: 製品概要メモ"
                  />
                </label>
                <label className="field">
                  資料テキスト
                  <textarea
                    value={textContent}
                    onChange={(event) => setTextContent(event.target.value)}
                    rows={5}
                    placeholder="根拠として使う文章を貼り付けてください"
                  />
                </label>
                <button
                  className="btn btn-sm"
                  type="button"
                  disabled={uploading || !textContent.trim()}
                  onClick={() => void handleTextDocument()}
                >
                  テキスト資料を登録
                </button>
              </div>
            </details>
            <div className="document-picker" aria-label="使用する資料">
              {documents.length === 0 ? (
                <p className="muted">登録済み資料はありません。資料なしでも作成できます。</p>
              ) : (
                documents.map((document) => (
                  <label className="document-option" key={document.id}>
                    <input
                      type="checkbox"
                      checked={(form.document_ids ?? []).includes(document.id)}
                      onChange={(event) => toggleDocument(document.id, event.target.checked)}
                    />
                    <span>
                      {document.title}
                      <small>
                        {String(document.metadata.original_format ?? document.source_type).toUpperCase()}
                        {' · '}{document.chunk_count}チャンク
                      </small>
                    </span>
                  </label>
                ))
              )}
            </div>
          </fieldset>
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
          <label className="field instructions-field">
            追加指示
            <textarea
              value={form.instructions}
              onChange={(event) => setForm({ ...form, instructions: event.target.value })}
              placeholder="例: 結論を先に示し、導入効果を数字で強調する。競合名は出さない。"
              rows={4}
            />
            <small>アウトラインと台本の生成に反映されます。資料本文とは分離して扱います。</small>
          </label>
          <div className="row" style={{ marginTop: 12 }}>
            <label className="row">
              <input
                type="checkbox"
                checked={form.auto_run}
                onChange={(e) => setForm({ ...form, auto_run: e.target.checked })}
              />
              作成後すぐに生成を開始する
            </label>
            <button className="btn btn-primary" type="submit" disabled={submitting || uploading}>
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
