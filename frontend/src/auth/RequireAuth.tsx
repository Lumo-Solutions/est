import type { ReactNode } from 'react'
import { useAuth } from './AuthContext'
import { LoginPage } from '../pages/LoginPage'

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center text-slate-500">
        Loading...
      </div>
    )
  }

  if (!user) {
    return <LoginPage />
  }

  return <>{children}</>
}
