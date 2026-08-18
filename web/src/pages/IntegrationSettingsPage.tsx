import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import {
  attestElevenLabsVoice,
  createElevenLabsVoiceClone,
  deleteIntegration,
  listElevenLabsVoices,
  listIntegrations,
  registerIntegration,
  revokeElevenLabsVoiceConsent,
} from '../api/endpoints'
import type { IntegrationView, Provider, VoiceInfo } from '../api/types'
import { API_KEY_PREFIXES, validateApiKeyPrefix } from './integrationKeyValidation'
import { validateVoiceCloneFiles } from './voiceCloneValidation'

const PROVIDERS: Array<{
  id: Provider
  name: string
  description: string
  hint: string
  permissionHint: string
}> = [
  {
    id: 'orcarouter',
    name: 'OrcaRouter',
    description: 'アウトライン・台本・Q&Aの生成に使用します。',
    hint: 'sk- から始まるAPIキー',
    permissionHint: '接続確認では GET /v1/models、ウェビナー構成・台本・Q&Aの生成では POST /v1/chat/completions を使用します。OrcaRouterのキー作成時に、モデル一覧の参照とチャット生成を実行できる権限を付与してください。有効期限・利用上限・IP制限も、接続または生成の失敗要因になり得ます。',
  },
  {
    id: 'elevenlabs',
    name: 'ElevenLabs',
    description: 'クローン音声によるナレーション生成に使用します。',
    hint: 'sk_ から始まるAPIキー',
    permissionHint: '接続確認では必須の GET /v1/voices（Voices Read）を使用し、音声生成では POST /v1/text-to-speech/{voice_id}（Text to Speech）、Voice Clone作成では POST /v1/voices/add（Voices Write）を使用します。GET /v1/user/subscription に必要な User Read（user_read）はプラン・使用量表示のための任意権限で、なくても接続できます。有効期限・IP allowlist・スコープ制限・クレジット上限も失敗要因になり得ます。Freeプランでは商用利用条件を確認し、下の確認欄にチェックしてください。',
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
  const [attestationVersion, setAttestationVersion] = useState<string | null>(null)
  const [consentChecks, setConsentChecks] = useState<Record<string, boolean>>({})
  const [busyVoice, setBusyVoice] = useState<string | null>(null)
  const [loadingVoices, setLoadingVoices] = useState(false)
  const [cloneName, setCloneName] = useState('')
  const [cloneDescription, setCloneDescription] = useState('')
  const [cloneFiles, setCloneFiles] = useState<File[]>([])
  const [removeBackgroundNoise, setRemoveBackgroundNoise] = useState(false)
  const [cloneConsent, setCloneConsent] = useState(false)
  const [cloning, setCloning] = useState(false)
  const cloneFileInput = useRef<HTMLInputElement>(null)

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
    const prefixError = validateApiKeyPrefix(provider, apiKey)
    if (prefixError) {
      setError(prefixError)
      setMessage(null)
      return
    }
    setBusy(provider)
    setMessage(null)
    try {
      await registerIntegration(provider, apiKey, provider === 'elevenlabs' && acceptFreeTier)
      setKeys((current) => ({ ...current, [provider]: '' }))
      if (provider === 'elevenlabs') {
        setVoices([])
        setAttestationVersion(null)
        setConsentChecks({})
      }
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
      if (provider === 'elevenlabs') {
        setVoices([])
        setAttestationVersion(null)
        setConsentChecks({})
      }
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
      const response = await listElevenLabsVoices()
      setVoices(response.voices)
      setAttestationVersion(response.attestation_version)
      setConsentChecks({})
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice一覧を取得できませんでした。')
    } finally {
      setLoadingVoices(false)
    }
  }

  function replaceVoice(updated: VoiceInfo) {
    setVoices((current) => {
      const exists = current.some((voice) => voice.voice_id === updated.voice_id)
      if (!exists) return [...current, updated]
      return current.map((voice) => voice.voice_id === updated.voice_id ? updated : voice)
    })
  }

  async function handleClone(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const filesError = validateVoiceCloneFiles(cloneFiles)
    if (filesError) {
      setError(filesError)
      return
    }
    if (!cloneConsent) {
      setError('話者本人の同意と利用権限を確認してください。')
      return
    }

    setCloning(true)
    setError(null)
    setMessage(null)
    try {
      let currentAttestationVersion = attestationVersion
      if (!currentAttestationVersion) {
        const response = await listElevenLabsVoices()
        setVoices(response.voices)
        setAttestationVersion(response.attestation_version)
        currentAttestationVersion = response.attestation_version
      }
      const response = await createElevenLabsVoiceClone({
        name: cloneName.trim(),
        description: cloneDescription.trim(),
        files: cloneFiles,
        removeBackgroundNoise,
        consentConfirmed: cloneConsent,
        attestationVersion: currentAttestationVersion,
      })
      replaceVoice(response.voice)
      setAttestationVersion(response.attestation_version)
      setCloneName('')
      setCloneDescription('')
      setCloneFiles([])
      setRemoveBackgroundNoise(false)
      setCloneConsent(false)
      if (cloneFileInput.current) cloneFileInput.current.value = ''
      setMessage(response.requires_verification
        ? `${response.voice.name} を作成しました。ElevenLabsでの本人確認完了後に利用できます。`
        : `${response.voice.name} を作成し、利用同意を記録しました。`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice Cloneを作成できませんでした。')
    } finally {
      setCloning(false)
    }
  }

  async function handleConsent(voice: VoiceInfo) {
    if (!attestationVersion || !consentChecks[voice.voice_id]) return
    setBusyVoice(voice.voice_id)
    setMessage(null)
    try {
      replaceVoice(await attestElevenLabsVoice(voice.voice_id, attestationVersion))
      setConsentChecks((current) => ({ ...current, [voice.voice_id]: false }))
      setMessage(`${voice.name} の利用同意を記録しました。`)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voiceの同意を記録できませんでした。')
    } finally {
      setBusyVoice(null)
    }
  }

  async function handleRevokeConsent(voice: VoiceInfo) {
    setBusyVoice(voice.voice_id)
    setMessage(null)
    try {
      replaceVoice(await revokeElevenLabsVoiceConsent(voice.voice_id))
      setMessage(`${voice.name} の利用同意を取り消しました。`)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voiceの同意を取り消せませんでした。')
    } finally {
      setBusyVoice(null)
    }
  }

  function voiceConsentLabel(voice: VoiceInfo): string {
    if (!voice.active) return '利用不可'
    if (voice.consent_status === 'not_required') return '同意不要（premade等）'
    if (voice.consent_status === 'attested' && voice.usable) return '同意済み・利用可'
    return '同意未取得・利用不可'
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
          const keyPrefix = API_KEY_PREFIXES[provider.id]
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
                  {provider.id === 'elevenlabs' && (
                    <form className="voice-clone-form" onSubmit={(event) => void handleClone(event)}>
                      <div className="voice-clone-heading">
                        <div>
                          <h3>Voice Cloneを作成</h3>
                          <p>明瞭な1〜2分の音声を推奨します。ノイズ・反響・複数話者は避けてください。</p>
                        </div>
                        <span>Instant</span>
                      </div>
                      <div className="field">
                        <label htmlFor="voice-clone-name">Voice名</label>
                        <input
                          id="voice-clone-name"
                          value={cloneName}
                          onChange={(event) => setCloneName(event.target.value)}
                          required
                          minLength={1}
                          maxLength={100}
                          placeholder="例: 田中 太郎"
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="voice-clone-description">説明（任意）</label>
                        <input
                          id="voice-clone-description"
                          value={cloneDescription}
                          onChange={(event) => setCloneDescription(event.target.value)}
                          maxLength={500}
                          placeholder="例: 日本語ウェビナー用"
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="voice-clone-files">サンプル音声</label>
                        <input
                          ref={cloneFileInput}
                          id="voice-clone-files"
                          type="file"
                          accept=".mp3,.wav,.m4a,.webm,audio/mpeg,audio/wav,audio/mp4,audio/webm"
                          multiple
                          required
                          onChange={(event) => {
                            const selected = Array.from(event.currentTarget.files ?? [])
                            const validationError = validateVoiceCloneFiles(selected)
                            if (validationError) {
                              setCloneFiles([])
                              setError(validationError)
                              event.currentTarget.value = ''
                              return
                            }
                            setCloneFiles(selected)
                            setError(null)
                          }}
                        />
                        <small>MP3 / WAV / M4A / WebM、最大5件、1件10 MiB・合計25 MiBまで</small>
                        {cloneFiles.length > 0 && <small>{cloneFiles.length}件の音声を選択中</small>}
                      </div>
                      <label className="consent-row">
                        <input
                          type="checkbox"
                          checked={removeBackgroundNoise}
                          onChange={(event) => setRemoveBackgroundNoise(event.target.checked)}
                        />
                        背景ノイズを除去する（元音声がクリアな場合はOFF推奨）
                      </label>
                      <label className="consent-row voice-clone-consent">
                        <input
                          type="checkbox"
                          checked={cloneConsent}
                          onChange={(event) => setCloneConsent(event.target.checked)}
                          required
                        />
                        私は話者本人、またはこの声をクローンし利用するための明示的な同意と権利を得ています
                      </label>
                      <button className="btn btn-primary" type="submit" disabled={cloning || busy !== null}>
                        {cloning ? '作成中…' : 'Voice Cloneを作成'}
                      </button>
                      <p className="voice-clone-privacy">音声はElevenLabsへ送信され、Koebinarには保存されません。</p>
                    </form>
                  )}
                </div>
              ) : (
                <form className="integration-form" onSubmit={(event) => void handleRegister(event, provider.id)}>
                  <div className="field">
                    <div className="field-label-row">
                      <label htmlFor={`${provider.id}-api-key`}>APIキー</label>
                      <details className="permission-hint">
                        <summary aria-label={`${provider.name} APIキーの必要権限を表示`}>[i]</summary>
                        <p>{provider.permissionHint}</p>
                      </details>
                    </div>
                    <input
                      id={`${provider.id}-api-key`}
                      type="password"
                      autoComplete="off"
                      required
                      pattern={`${keyPrefix}.*`}
                      title={`${provider.name}のAPIキーは ${keyPrefix} から始まる必要があります`}
                      aria-describedby={`${provider.id}-api-key-prefix`}
                      value={keys[provider.id]}
                      onChange={(event) => setKeys((current) => ({ ...current, [provider.id]: event.target.value }))}
                      onInvalid={(event) => {
                        const current = event.currentTarget.value.trim()
                        setError(current
                          ? validateApiKeyPrefix(provider.id, current)
                          : `${provider.name}のAPIキーを入力してください。`)
                      }}
                      placeholder={provider.hint}
                    />
                    <small id={`${provider.id}-api-key-prefix`}>
                      {provider.name}のAPIキーは {keyPrefix} から始まります
                    </small>
                  </div>
                  {provider.id === 'elevenlabs' && (
                    <label className="consent-row">
                      <input type="checkbox" checked={acceptFreeTier} onChange={(event) => setAcceptFreeTier(event.target.checked)} />
                      Freeプランの場合の商用利用制限・表示条件を確認しました
                    </label>
                  )}
                  <button className="btn btn-primary" type="submit" disabled={busy !== null}>
                    {busy === provider.id ? '検証中…' : '検証して接続'}
                  </button>
                  {provider.id === 'elevenlabs' && (
                    <p className="voice-clone-privacy">接続後に、この画面からVoice Cloneを作成できます。</p>
                  )}
                </form>
              )}
            </section>
          )
        })}
      </div>

      {voices.length > 0 && (
        <section className="card voice-section">
          <div>
            <p className="eyebrow">ELEVENLABS</p>
            <h2>利用可能なVoice</h2>
            <p className="voice-consent-help">
              クローンVoiceは、話者本人から必要な同意を取得済みであることを確認してから、Voiceごとに利用同意を記録してください。Voice一覧の取得だけでは同意されません。
            </p>
          </div>
          <ul className="voice-list">
            {voices.map((voice) => (
              <li key={voice.voice_id}>
                <div className="voice-heading">
                  <strong>{voice.name}</strong>
                  <span className={`voice-consent-status status-${voice.consent_status}`}>
                    {voiceConsentLabel(voice)}
                  </span>
                </div>
                <span>カテゴリ: {voice.category}</span>
                <code>{voice.voice_id}</code>
                {voice.attested_at && (
                  <span>同意記録: {new Date(voice.attested_at).toLocaleString('ja-JP')}</span>
                )}
                {voice.consent_status === 'required' && voice.active && (
                  <>
                    <label className="consent-row voice-consent-row">
                      <input
                        type="checkbox"
                        checked={Boolean(consentChecks[voice.voice_id])}
                        onChange={(event) => setConsentChecks((current) => ({
                          ...current,
                          [voice.voice_id]: event.target.checked,
                        }))}
                        disabled={busyVoice !== null}
                      />
                      <span>話者本人の同意取得と、このVoiceの利用条件を確認しました</span>
                    </label>
                    <button
                      className="btn btn-primary"
                      type="button"
                      onClick={() => void handleConsent(voice)}
                      disabled={!attestationVersion || !consentChecks[voice.voice_id] || busyVoice !== null}
                    >
                      {busyVoice === voice.voice_id ? '記録中…' : '利用同意を記録'}
                    </button>
                  </>
                )}
                {voice.consent_status === 'attested' && (
                  <button
                    className="btn btn-danger"
                    type="button"
                    onClick={() => void handleRevokeConsent(voice)}
                    disabled={busyVoice !== null}
                  >
                    {busyVoice === voice.voice_id ? '取消中…' : '利用同意を取り消す'}
                  </button>
                )}
                {voice.consent_status === 'not_required' && (
                  <span className="voice-consent-note">提供元の免除カテゴリのため、テナント同意は不要です。</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
