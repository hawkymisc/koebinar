/* oxlint-disable react/only-export-components */
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { clearSession, getStoredTenant, getToken, setSession } from '../api/client'
import { getSession, login } from '../api/endpoints'
import type { Tenant } from '../api/types'

interface AuthContextValue {
  tenant: Tenant | null
  checking: boolean
  signIn: (workspaceId: string, accessToken: string) => Promise<void>
  signOut: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [tenant, setTenant] = useState<Tenant | null>(getStoredTenant())
  const [checking, setChecking] = useState(Boolean(getToken()))

  useEffect(() => {
    const token = getToken()
    if (!token) {
      setChecking(false)
      return
    }
    void getSession()
      .then((response) => {
        setSession(token, response.tenant)
        setTenant(response.tenant)
      })
      .catch(() => {
        clearSession()
        setTenant(null)
      })
      .finally(() => setChecking(false))
  }, [])

  useEffect(() => {
    const handleUnauthorized = () => setTenant(null)
    window.addEventListener('koebinar:unauthorized', handleUnauthorized)
    return () => window.removeEventListener('koebinar:unauthorized', handleUnauthorized)
  }, [])

  async function signIn(workspaceId: string, accessToken: string) {
    const response = await login(workspaceId, accessToken)
    setSession(response.token, response.tenant)
    setTenant(response.tenant)
  }

  function signOut() {
    clearSession()
    setTenant(null)
  }

  return (
    <AuthContext.Provider value={{ tenant, checking, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
