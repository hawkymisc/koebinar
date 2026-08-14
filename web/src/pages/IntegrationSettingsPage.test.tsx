import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { IntegrationSettingsPage } from './IntegrationSettingsPage'
import { validateApiKeyPrefix } from './integrationKeyValidation'

describe('IntegrationSettingsPage provider permission hints', () => {
  it('rejects API keys whose provider prefix is missing or incorrect', () => {
    expect(validateApiKeyPrefix('elevenlabs', 'sk_valid-elevenlabs-key')).toBeNull()
    expect(validateApiKeyPrefix('orcarouter', 'sk-valid-orcarouter-key')).toBeNull()

    expect(validateApiKeyPrefix('elevenlabs', 'valid-elevenlabs-key')).toContain('sk_')
    expect(validateApiKeyPrefix('elevenlabs', 'sk-valid-elevenlabs-key')).toContain('キーIDではなくAPIキー全文')
    expect(validateApiKeyPrefix('orcarouter', 'valid-orcarouter-key')).toContain('sk-')
    expect(validateApiKeyPrefix('orcarouter', 'sk_valid-orcarouter-key')).toContain('キーIDではなくAPIキー全文')
  })

  it('declares provider-specific prefix constraints on both key fields', () => {
    const html = renderToStaticMarkup(<IntegrationSettingsPage />)

    expect(html).toContain('id="orcarouter-api-key"')
    expect(html).toContain('pattern="sk-.*"')
    expect(html).toContain('OrcaRouterのAPIキーは sk- から始まります')
    expect(html).toContain('id="elevenlabs-api-key"')
    expect(html).toContain('pattern="sk_.*"')
    expect(html).toContain('ElevenLabsのAPIキーは sk_ から始まります')
  })

  it('documents the OrcaRouter validation and generation access requirements', () => {
    const html = renderToStaticMarkup(<IntegrationSettingsPage />)

    expect(html).toContain('aria-label="OrcaRouter APIキーの必要権限を表示"')
    expect(html).toContain('GET /v1/models')
    expect(html).toContain('POST /v1/chat/completions')
    expect(html).toContain('モデル一覧の参照とチャット生成')
    expect(html).toContain('有効期限・利用上限・IP制限')
  })

  it('documents the ElevenLabs validation, TTS, and Free-plan requirements', () => {
    const html = renderToStaticMarkup(<IntegrationSettingsPage />)

    expect(html).toContain('aria-label="ElevenLabs APIキーの必要権限を表示"')
    expect(html).toContain('GET /v1/user/subscription')
    expect(html).toContain('GET /v1/voices')
    expect(html).toContain('POST /v1/text-to-speech/{voice_id}')
    expect(html).toContain('任意')
    expect(html).toContain('User Read（user_read）')
    expect(html).toContain('有効期限・IP allowlist・スコープ制限')
    expect(html).toContain('Freeプランでは商用利用条件を確認し、下の確認欄にチェックしてください')
  })

  it('uses native disclosure controls consistently for keyboard and pointer access', () => {
    const html = renderToStaticMarkup(<IntegrationSettingsPage />)

    expect(html.match(/<details class="permission-hint"/g)).toHaveLength(2)
    expect(html.match(/<summary/g)).toHaveLength(2)
    expect(html.match(/>\[i\]<\/summary>/g)).toHaveLength(2)
  })
})
