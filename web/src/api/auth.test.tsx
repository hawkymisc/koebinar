import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearSession, getStoredTenant, getToken, setSession } from './client'
import { deleteIntegration, getSession, listIntegrations, login, registerIntegration } from './endpoints'
import { LoginForm } from '../pages/LoginPage'
import { Sidebar } from '../components/Sidebar'

function mockFetch(body: unknown, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    } as Response),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('operator session', () => {
  it('stores and clears the tenant with its bearer token', () => {
    setSession('acme-secret', { id: 'acme', name: 'Acme株式会社' })
    expect(getToken()).toBe('acme-secret')
    expect(getStoredTenant()).toEqual({ id: 'acme', name: 'Acme株式会社' })

    clearSession()
    expect(getToken()).toBe('')
    expect(getStoredTenant()).toBeNull()
  })

  it('uses the documented login and session endpoints', async () => {
    mockFetch({ tenant: { id: 'acme', name: 'Acme株式会社' }, token: 'acme-secret' })
    await login('acme', 'acme-secret')
    let [url, options] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(String(url)).toContain('/auth/login')
    expect(options.body).toBe(JSON.stringify({ workspace_id: 'acme', access_token: 'acme-secret' }))
    expect((options.headers as Record<string, string>).Authorization).toBeUndefined()

    setSession('acme-secret', { id: 'acme', name: 'Acme株式会社' })
    mockFetch({ tenant: { id: 'acme', name: 'Acme株式会社' } })
    await getSession()
    ;[url, options] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(String(url)).toContain('/auth/session')
    expect((options.headers as Record<string, string>).Authorization).toBe('Bearer acme-secret')
  })
})

describe('integration settings API', () => {
  it('lists, registers, and deletes tenant integrations', async () => {
    setSession('acme-secret', { id: 'acme', name: 'Acme株式会社' })
    mockFetch([])
    await listIntegrations()
    expect(String((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0])).toContain('/integrations')

    mockFetch({ provider: 'orcarouter', status: 'active' })
    await registerIntegration('orcarouter', 'orca-key', false)
    let [, options] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(options.method).toBe('POST')
    expect(options.body).toBe(JSON.stringify({ api_key: 'orca-key', accept_free_tier: false }))

    mockFetch({ status: 'deleted' })
    await deleteIntegration('orcarouter')
    ;[, options] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(options.method).toBe('DELETE')
  })
})

describe('operator navigation', () => {
  it('renders login fields and tenant-aware sidebar destinations', () => {
    const loginHtml = renderToStaticMarkup(
      <LoginForm submitting={false} error={null} onSubmit={() => undefined} />,
    )
    expect(loginHtml).toContain('ワークスペースID')
    expect(loginHtml).toContain('アクセストークン')

    const sidebarHtml = renderToStaticMarkup(
      <MemoryRouter>
        <Sidebar tenant={{ id: 'acme', name: 'Acme株式会社' }} onLogout={() => undefined} />
      </MemoryRouter>,
    )
    expect(sidebarHtml).toContain('Acme株式会社')
    expect(sidebarHtml).toContain('ウェビナー')
    expect(sidebarHtml).toContain('連携設定')
    expect(sidebarHtml).toContain('href="/settings/integrations"')
  })
})
