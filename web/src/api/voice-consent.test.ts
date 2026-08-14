import { afterEach, describe, expect, it, vi } from 'vitest'
import { setToken } from './client'
import {
  attestElevenLabsVoice,
  listElevenLabsVoices,
  revokeElevenLabsVoiceConsent,
} from './endpoints'

function mockFetch(body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => body,
    } as Response),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('voice consent API', () => {
  it('keeps the provider list response and attestation version together', async () => {
    setToken('acme-token')
    const response = {
      voices: [{
        voice_id: 'voice_clone/ja',
        name: 'Clone',
        category: 'cloned',
        labels: {},
        active: true,
        consent_status: 'required',
        consent_source: null,
        attested_at: null,
        attested_by: null,
        attestation_version: null,
        usable: false,
      }],
      attestation_version: 'voice-consent-v1',
    }
    mockFetch(response)

    await expect(listElevenLabsVoices()).resolves.toEqual(response)
    const [url, options] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(String(url)).toContain('/integrations/elevenlabs/voices')
    expect((options.headers as Record<string, string>).Authorization).toBe('Bearer acme-token')
  })

  it('posts explicit acceptance and supports revocation for the same Voice', async () => {
    setToken('acme-token')
    const updated = {
      voice_id: 'voice_clone/ja',
      name: 'Clone',
      category: 'cloned',
      labels: {},
      active: true,
      consent_status: 'attested',
      consent_source: 'operator_attestation',
      attested_at: '2026-08-14T01:02:03Z',
      attested_by: 'acme',
      attestation_version: 'voice-consent-v1',
      usable: true,
    }
    mockFetch(updated)
    await attestElevenLabsVoice('voice_clone/ja', 'voice-consent-v1')
    let [url, options] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(String(url)).toContain('/voices/voice_clone%2Fja/consent')
    expect(options.method).toBe('POST')
    expect(options.body).toBe(JSON.stringify({ accepted: true, attestation_version: 'voice-consent-v1' }))

    mockFetch({ ...updated, consent_status: 'required', consent_source: null, usable: false })
    await revokeElevenLabsVoiceConsent('voice_clone/ja')
    ;[url, options] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(String(url)).toContain('/voices/voice_clone%2Fja/consent')
    expect(options.method).toBe('DELETE')
  })
})
