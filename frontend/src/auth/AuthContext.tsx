import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError, api } from '../lib/api'

export interface AuthUser {
  sub: string
  // Login name for display (Keycloak preferred_username); null if the token has none.
  username: string | null
  tenantId: string
  roles: string[]
  acr: string | null
  // Backend's DEV_DISABLE_MFA is active (dev/test only) -- drives the banner.
  mfaDisabledDev: boolean
}

interface AuthMeResponse {
  sub: string
  username?: string | null
  tenant_id: string
  roles: string[]
  acr: string | null
  mfa_disabled_dev?: boolean
}

interface AuthContextValue {
  user: AuthUser | null
  isLoading: boolean
  hasRole: (...roles: string[]) => boolean
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const me = await api.get<AuthMeResponse>('/auth/me')
      setUser({
        sub: me.sub,
        username: me.username ?? null,
        tenantId: me.tenant_id,
        roles: me.roles,
        acr: me.acr,
        mfaDisabledDev: me.mfa_disabled_dev === true,
      })
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setUser(null)
      } else {
        throw err
      }
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const hasRole = useCallback(
    (...roles: string[]) => (user ? roles.some((role) => user.roles.includes(role)) : false),
    [user],
  )

  return <AuthContext.Provider value={{ user, isLoading, hasRole, refresh }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
