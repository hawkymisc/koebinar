import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IntegrationSettingsPage } from './IntegrationSettingsPage'
import { validateApiKeyPrefix } from './integrationKeyValidation'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

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
    expect(html).toContain('POST /v1/voices/add')
    expect(html).toContain('Voices Write')
    expect(html).toContain('任意')
    expect(html).toContain('User Read（user_read）')
    expect(html).toContain('有効期限・IP allowlist・スコープ制限')
    expect(html).toContain('Freeプランでは商用利用条件を確認し、下の確認欄にチェックしてください')
  })

  it('renders the in-app Instant Voice Clone controls and explicit rights confirmation', () => {
    const html = renderToStaticMarkup(<IntegrationSettingsPage />)

    expect(html).toContain('接続後に、この画面からVoice Cloneを作成できます')
  })

  it('renders the complete clone form after ElevenLabs is connected', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [{
        id: 'int-elevenlabs',
        provider: 'elevenlabs',
        key_mask: 'sk_...1234',
        status: 'active',
        validated_at: '2026-08-17T00:00:00Z',
        meta: {},
      }],
    } as Response))
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)

    await act(async () => {
      root.render(<IntegrationSettingsPage />)
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    expect(container.querySelector('#voice-clone-name')).not.toBeNull()
    expect(container.querySelector('#voice-clone-files')).not.toBeNull()
    expect(container.textContent).toContain('話者本人')
    expect(container.textContent).toContain('Koebinarには保存されません')

    await act(async () => root.unmount())
  })

  it('uses native disclosure controls consistently for keyboard and pointer access', () => {
    const html = renderToStaticMarkup(<IntegrationSettingsPage />)

    expect(html.match(/<details class="permission-hint"/g)).toHaveLength(2)
    expect(html.match(/<summary/g)).toHaveLength(2)
    expect(html.match(/>\[i\]<\/summary>/g)).toHaveLength(2)
  })
})
