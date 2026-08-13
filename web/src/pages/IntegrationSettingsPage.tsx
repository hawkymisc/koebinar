import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import {
  deleteIntegration,
  listElevenLabsVoices,
  listIntegrations,
  registerIntegration,
} from '../api/endpoints'
import type { IntegrationView, Provider, VoiceInfo } from '../api/types'

const PROVIDERS: Array<{
  id: Provider
  name: string
  description: string
  hint: string
}> = [
  {
    id: 'orcarouter',
    name: 'OrcaRouter',
    description: 'アウトライン・台本・Q&Aの生成に使用します。',
    hint: 'モデル一覧の読み取り権限を持つキー',
  },
  {
    id: 'elevenlabs',
    name: 'ElevenLabs',
    description: 'クローン音声によるナレーション生成に使用します。',
    hint: 'TTSとVoices読み取り権限を持つキー',
  },
]

function usageLabel(integration: IntegrationView): string | null {
  const used = integration.meta.character_count
  const limit = integration.meta.character_limit
  if (typeof used !== 'number' || typeof limit !== 'number') return null
  return `${used.toLocaleString()} / ${limit.toLocaleString()} 文字`
}

export function IntegrationSettingsPage() {
  const [integrations, setIntegrations] = useState<IntegrationView[]>([])
  const [keys, setKeys] = useState<Record<Provider, string>>({ orcarouter: '', elevenlabs: '' })
  const [acceptFreeTier, setAcceptFreeTier] = useState(false)
  const [busy, setBusy] = useState<Provider | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [voices, setVoices] = useState<VoiceInfo[]>([])
  const [loadingVoices, setLoadingVoices] = useState(false)

  const byProvider = useMemo(
    () => new Map(integrations.map((integration) => [integration.provider, integration])),
    [integrations],
  )

  async function reload() {
    try {
      setIntegrations(await listIntegrations())
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '連携状態を取得できませんでした。')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void reload()
  }, [])

  async function handleRegister(event: FormEvent, provider: Provider) {
    event.preventDefault()
    const apiKey = keys[provider].trim()
    if (!apiKey) return
    setBusy(provider)
    setMessage(null)
    try {
      await registerIntegration(provider, apiKey, provider === 'elevenlabs' && acceptFreeTier)
      setKeys((current) => ({ ...current, [provider]: '' }))
      setMessage(`${PROVIDERS.find((item) => item.id === provider)?.name} を接続しました。`)
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'APIキーを検証できませんでした。')
    } finally {
      setBusy(null)
    }
  }

  async function handleDelete(provider: Provider) {
    setBusy(provider)
    setMessage(null)
    try {
      await deleteIntegration(provider)
      if (provider === 'elevenlabs') setVoices([])
      setMessage('連携を解除しました。')
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : '連携を解除できませんでした。')
    } finally {
      setBusy(null)
    }
  }

  async function handleVoices() {
    setLoadingVoices(true)
    try {
      setVoices(await listElevenLabsVoices())
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice一覧を取得できませんでした。')
    } finally {
      setLoadingVoices(false)
    }
  }

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">SETTINGS</p>
          <h1>連携設定</h1>
          <p>このワークスペース専用のAPIキーを登録します。キーは暗号化して保存され、画面には再表示されません。</p>
        </div>
      </header>

      {error && <p className="error-box" role="alert">{error}</p>}
      {message && <p className="success-box" role="status">{message}</p>}

      <div className="integration-grid" aria-busy={loading}>
        {PROVIDERS.map((provider) => {
          const integration = byProvider.get(provider.id)
          const connected = integration?.status === 'active'
          const usage = integration ? usageLabel(integration) : null
          const warnings = integration?.meta.warnings ?? []
          return (
            <section className="integration-card" key={provider.id}>
              <div className="integration-heading">
                <div className={`provider-mark provider-${provider.id}`} aria-hidden="true">
                  {provider.id === 'orcarouter' ? 'O' : '11'}
                </div>
                <div>
                  <h2>{provider.name}</h2>
                  <p>{provider.description}</p>
                </div>
                <span className={`connection-state ${connected ? 'is-connected' : ''}`}>
                  {connected ? '接続済み' : '未接続'}
                </span>
              </div>

              {connected && integration ? (
                <div className="integration-details">
                  <dl>
                    <div><dt>APIキー</dt><dd>{integration.key_mask}</dd></div>
                    <div>
                      <dt>最終検証</dt>
                      <dd>{integration.validated_at ? new Date(integration.validated_at).toLocaleString('ja-JP') : '—'}</dd>
                    </div>
                    {integration.meta.tier && <div><dt>プラン</dt><dd>{String(integration.meta.tier)}</dd></div>}
                    {usage && <div><dt>使用量</dt><dd>{usage}</dd></div>}
                    {typeof integration.meta.model_count === 'number' && (
                      <div><dt>利用可能モデル</dt><dd>{integration.meta.model_count}件</dd></div>
                    )}
                  </dl>
                  {warnings.map((warning) => <p className="warning-box" key={warning}>{warning}</p>)}
                  <div className="integration-actions">
                    {provider.id === 'elevenlabs' && (
                      <button className="btn" type="button" onClick={() => void handleVoices()} disabled={loadingVoices}>
                        {loadingVoices ? '取得中…' : 'Voice一覧を取得'}
                      </button>
                    )}
                    <button className="btn btn-danger" type="button" onClick={() => void handleDelete(provider.id)} disabled={busy !== null}>
                      連携を解除
                    </button>
                  </div>
                </div>
              ) : (
                <form className="integration-form" onSubmit={(event) => void handleRegister(event, provider.id)}>
                  <label className="field">
                    APIキー
                    <input
                      type="password"
                      autoComplete="off"
                      required
                      value={keys[provider.id]}
                      onChange={(event) => setKeys((current) => ({ ...current, [provider.id]: event.target.value }))}
                      placeholder={provider.hint}
                    />
                  </label>
                  {provider.id === 'elevenlabs' && (
                    <label className="consent-row">
                      <input type="checkbox" checked={acceptFreeTier} onChange={(event) => setAcceptFreeTier(event.target.checked)} />
                      Freeプランの場合の商用利用制限・表示条件を確認しました
                    </label>
                  )}
                  <button className="btn btn-primary" type="submit" disabled={busy !== null}>
                    {busy === provider.id ? '検証中…' : '検証して接続'}
                  </button>
                </form>
              )}
            </section>
          )
        })}
      </div>

      {voices.length > 0 && (
        <section className="card voice-section">
          <div><p className="eyebrow">ELEVENLABS</p><h2>利用可能なVoice</h2></div>
          <ul className="voice-list">
            {voices.map((voice) => (
              <li key={voice.voice_id}>
                <strong>{voice.name}</strong>
                <span>{voice.category}</span>
                <code>{voice.voice_id}</code>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
