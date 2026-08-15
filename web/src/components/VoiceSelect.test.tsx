import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { VoiceInfo } from '../api/types'
import { VoiceSelect } from './VoiceSelect'
import { usableVoices } from './voiceOptions'

function voice(overrides: Partial<VoiceInfo>): VoiceInfo {
  return {
    voice_id: 'voice-usable',
    name: 'Usable voice',
    category: 'premade',
    labels: {},
    active: true,
    consent_status: 'not_required',
    consent_source: null,
    attested_at: null,
    attested_by: null,
    attestation_version: null,
    usable: true,
    ...overrides,
  }
}

describe('VoiceSelect', () => {
  it('offers only active, usable provider voices and never a default pseudo voice', () => {
    const voices = [
      voice({ voice_id: 'voice-usable', name: 'Sarah' }),
      voice({ voice_id: 'voice-consent', name: 'Clone', usable: false, consent_status: 'required' }),
      voice({ voice_id: 'voice-inactive', name: 'Old', active: false }),
    ]

    expect(usableVoices(voices).map((item) => item.voice_id)).toEqual(['voice-usable'])
    const html = renderToStaticMarkup(
      <VoiceSelect id="voice" voices={voices} value="voice-usable" onChange={() => undefined} />,
    )

    expect(html).toContain('required=""')
    expect(html).toContain('value="voice-usable"')
    expect(html).toContain('Sarah')
    expect(html).not.toContain('voice-consent')
    expect(html).not.toContain('voice-inactive')
    expect(html).not.toContain('value="default"')
  })

  it('disables selection and links to integration settings when no voice is usable', () => {
    const html = renderToStaticMarkup(
      <VoiceSelect id="voice" voices={[]} value="" onChange={() => undefined} />,
    )

    expect(html).toContain('disabled=""')
    expect(html).toContain('/settings/integrations')
    expect(html).toContain('利用可能な音声がありません')
  })
})
