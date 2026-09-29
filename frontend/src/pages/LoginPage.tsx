import { loginUrl } from '../lib/api'

export function LoginPage() {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-4 bg-canvas">
      <h1 className="text-2xl font-semibold text-ink">InstallTec Estimating</h1>
      <p className="text-muted">Sign in with your company account to continue.</p>
      <a
        href={loginUrl()}
        className="rounded-md bg-slate-800 px-4 py-2 font-medium text-white hover:bg-slate-700"
      >
        Sign in
      </a>
    </div>
  )
}
