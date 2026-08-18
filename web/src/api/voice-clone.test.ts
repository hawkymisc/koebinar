import { afterEach, describe, expect, it, vi } from 'vitest'
import { setToken } from './client'
import { createElevenLabsVoiceClone } from './endpoints'
import { validateVoiceCloneFiles } from '../pages/voiceCloneValidation'

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('ElevenLabs voice clone', () => {
  it('sends samples and consent as authenticated multipart data', async () => {
    setToken('acme-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ voice: { voice_id: 'voice-1' }, requires_verification: false }),
    } as Response))
    const sample = new File(['audio'], 'speaker.mp3', { type: 'audio/mpeg' })

    await createElevenLabsVoiceClone({
      name: 'Speaker',
      description: 'Japanese narrator',
      files: [sample],
      removeBackgroundNoise: false,
      consentConfirmed: true,
      attestationVersion: 'voice-consent-v1',
    })

    const [url, options] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(String(url)).toContain('/integrations/elevenlabs/voices/clone')
    expect(options.method).toBe('POST')
    expect((options.headers as Record<string, string>).Authorization).toBe('Bearer acme-token')
    expect((options.headers as Record<string, string>)['Content-Type']).toBeUndefined()
    const body = options.body as FormData
    expect(body.get('name')).toBe('Speaker')
    expect(body.get('consent_confirmed')).toBe('true')
    expect(body.get('attestation_version')).toBe('voice-consent-v1')
    expect(body.getAll('files')).toHaveLength(1)
  })

  it('validates type, empty samples, per-file size, and combined size', () => {
    expect(validateVoiceCloneFiles([])).toContain('1〜5件')
    expect(validateVoiceCloneFiles([new File(['x'], 'speaker.txt')])).toContain('MP3')
    expect(validateVoiceCloneFiles([new File([], 'speaker.mp3')])).toContain('空')
    expect(validateVoiceCloneFiles([
      new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'speaker.mp3'),
    ])).toContain('10 MiB')
    expect(validateVoiceCloneFiles([
      new File([new Uint8Array(9 * 1024 * 1024)], 'one.mp3'),
      new File([new Uint8Array(9 * 1024 * 1024)], 'two.wav'),
      new File([new Uint8Array(8 * 1024 * 1024)], 'three.m4a'),
    ])).toContain('25 MiB')
  })
})
