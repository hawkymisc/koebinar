import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'

interface LoginFormProps {
  submitting: boolean
  error: string | null
  onSubmit: (workspaceId: string, accessToken: string) => void | Promise<void>
}

export function LoginForm({ submitting, error, onSubmit }: LoginFormProps) {
  const [workspaceId, setWorkspaceId] = useState('default')
  const [accessToken, setAccessToken] = useState('')

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    void onSubmit(workspaceId.trim(), accessToken)
  }

  return (
    <form className="login-card" onSubmit={handleSubmit}>
      <div className="login-logo" aria-hidden="true">K</div>
      <p className="eyebrow">KOEBINAR CONSOLE</p>
      <h1>ワークスペースへログイン</h1>
      <p className="login-copy">ウェビナーと音声連携を、安全な組織領域で管理します。</p>
      <label className="field">
        ワークスペースID
        <input
          required
          autoComplete="organization"
          value={workspaceId}
          onChange={(event) => setWorkspaceId(event.target.value)}
          placeholder="acme"
        />
      </label>
      <label className="field">
        アクセストークン
        <input
          required
          type="password"
          autoComplete="current-password"
          value={accessToken}
          onChange={(event) => setAccessToken(event.target.value)}
          placeholder="••••••••••••"
        />
      </label>
      {error && <p className="error-box" role="alert">{error}</p>}
      <button className="btn btn-primary login-submit" type="submit" disabled={submitting}>
        {submitting ? '確認中…' : 'ログイン'}
      </button>
      <small className="login-help">ワークスペース情報は管理者から受け取ってください。</small>
    </form>
  )
}

export function LoginPage() {
  const { tenant, checking, signIn } = useAuth()
  const navigate = useNavigate()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!checking && tenant) return <Navigate to="/" replace />

  async function handleLogin(workspaceId: string, accessToken: string) {
    setSubmitting(true)
    try {
      await signIn(workspaceId, accessToken)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401
        ? 'ワークスペースIDまたはアクセストークンが正しくありません。'
        : err instanceof Error ? err.message : 'ログインできませんでした。')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <div className="login-ambient login-ambient-one" />
      <div className="login-ambient login-ambient-two" />
      <LoginForm submitting={submitting || checking} error={error} onSubmit={handleLogin} />
    </main>
  )
}
