import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiRequest, getStoredTenant, getToken, setSession, setToken } from './client'
import { createPublicQuestion, getPublicWebinar } from './endpoints'

function mockFetchOnce(body: unknown, init: { status?: number; ok?: boolean } = {}) {
  const status = init.status ?? 200
  const ok = init.ok ?? (status >= 200 && status < 300)
  const response = {
    ok,
    status,
    json: async () => body,
  } as Response
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
}

describe('apiRequest', () => {
  beforeEach(() => {
    setToken('mvp-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('sends the bearer token and parses a JSON success response', async () => {
    mockFetchOnce({ id: 'web_1', theme: 'Demo' })
    const result = await apiRequest<{ id: string; theme: string }>('/webinars/web_1')
    expect(result).toEqual({ id: 'web_1', theme: 'Demo' })

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>
    const [url, options] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/webinars/web_1')
    expect((options.headers as Record<string, string>).Authorization).toBe('Bearer mvp-token')
  })

  it('sends a JSON body with Content-Type for POST requests', async () => {
    mockFetchOnce({ id: 'web_2' })
    await apiRequest('/webinars', { method: 'POST', body: { theme: 'Demo' } })

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>
    const [, options] = fetchMock.mock.calls[0]
    expect(options.method).toBe('POST')
    expect((options.headers as Record<string, string>)['Content-Type']).toBe('application/json')
    expect(options.body).toBe(JSON.stringify({ theme: 'Demo' }))
  })

  it('throws ApiError with the parsed detail on a non-2xx response', async () => {
    mockFetchOnce({ detail: 'webinar not found' }, { status: 404, ok: false })
    await expect(apiRequest('/webinars/missing')).rejects.toMatchObject(
      new ApiError(404, 'webinar not found'),
    )
  })

  it('keeps the operator session when provider validation returns 422', async () => {
    setSession('acme-secret', { id: 'acme', name: 'Acme株式会社' })
    const unauthorized = vi.fn()
    window.addEventListener('koebinar:unauthorized', unauthorized)
    mockFetchOnce({ detail: 'ElevenLabs APIキーを検証できませんでした' }, { status: 422, ok: false })

    await expect(apiRequest('/integrations/elevenlabs', { method: 'POST' })).rejects.toMatchObject({
      status: 422,
    })
    expect(getToken()).toBe('acme-secret')
    expect(getStoredTenant()).toEqual({ id: 'acme', name: 'Acme株式会社' })
    expect(unauthorized).not.toHaveBeenCalled()
    window.removeEventListener('koebinar:unauthorized', unauthorized)
  })

  it('clears the operator session when session validation returns 401', async () => {
    setSession('acme-secret', { id: 'acme', name: 'Acme株式会社' })
    const unauthorized = vi.fn()
    window.addEventListener('koebinar:unauthorized', unauthorized)
    mockFetchOnce({ detail: 'invalid bearer token' }, { status: 401, ok: false })

    await expect(apiRequest('/auth/session')).rejects.toMatchObject({ status: 401 })
    expect(getToken()).toBe('')
    expect(getStoredTenant()).toBeNull()
    expect(unauthorized).toHaveBeenCalledOnce()
    window.removeEventListener('koebinar:unauthorized', unauthorized)
  })

  it('persists the token across getToken/setToken', () => {
    setToken('custom-token')
    expect(getToken()).toBe('custom-token')
  })

  it('does not invent or send an operator token when none is configured', async () => {
    localStorage.clear()
    mockFetchOnce([])
    await apiRequest('/webinars')
    expect(getToken()).toBe('')

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>
    const [, options] = fetchMock.mock.calls[0]
    expect((options.headers as Record<string, string>).Authorization).toBeUndefined()
  })

  it('does not send the operator token to public viewer endpoints', async () => {
    mockFetchOnce({ id: 'web_public', theme: 'Public webinar' })
    await getPublicWebinar('web_public')

    let fetchMock = fetch as unknown as ReturnType<typeof vi.fn>
    let [, options] = fetchMock.mock.calls[0]
    expect((options.headers as Record<string, string>).Authorization).toBeUndefined()

    mockFetchOnce({ id: 'q_public', status: 'pending' })
    await createPublicQuestion('web_public', '質問です')
    fetchMock = fetch as unknown as ReturnType<typeof vi.fn>
    ;[, options] = fetchMock.mock.calls[0]
    expect((options.headers as Record<string, string>).Authorization).toBeUndefined()
  })
})
