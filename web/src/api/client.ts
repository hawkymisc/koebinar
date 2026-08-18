import type { Tenant } from './types'

const TOKEN_STORAGE_KEY = 'koebinar.apiToken'
const TENANT_STORAGE_KEY = 'koebinar.tenant'

export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://127.0.0.1:8000/api/v1'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_STORAGE_KEY) ?? ''
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token)
}

export function getStoredTenant(): Tenant | null {
  const raw = localStorage.getItem(TENANT_STORAGE_KEY)
  if (!raw) return null
  try {
    const tenant = JSON.parse(raw) as Partial<Tenant>
    return tenant.id && tenant.name ? { id: tenant.id, name: tenant.name } : null
  } catch {
    return null
  }
}

export function setSession(token: string, tenant: Tenant): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token)
  localStorage.setItem(TENANT_STORAGE_KEY, JSON.stringify(tenant))
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
  localStorage.removeItem(TENANT_STORAGE_KEY)
}

interface ApiRequestOptions {
  method?: string
  body?: unknown
  auth?: boolean
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = true } = options
  const headers: Record<string, string> = {}
  if (auth) {
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }
  let payload: BodyInit | undefined
  if (body !== undefined) {
    if (body instanceof FormData) {
      payload = body
    } else {
      headers['Content-Type'] = 'application/json'
      payload = JSON.stringify(body)
    }
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: payload,
  })

  if (!response.ok) {
    const data = await response.json().catch(() => ({}) as { detail?: string })
    if (auth && response.status === 401) {
      clearSession()
      window.dispatchEvent(new Event('koebinar:unauthorized'))
    }
    throw new ApiError(response.status, data.detail ?? response.statusText)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}
