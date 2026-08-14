import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { IntegrationSettingsPage } from './IntegrationSettingsPage'

describe('IntegrationSettingsPage provider permission hints', () => {
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
