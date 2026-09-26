import { loginUrl } from '../lib/api'

export function LoginPage() {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-4 bg-slate-50">
      <h1 className="text-2xl font-semibold text-slate-800">InstallTec Estimating</h1>
      <p className="text-slate-500">Sign in with your company account to continue.</p>
      <a
        href={loginUrl()}
        className="rounded-md bg-slate-800 px-4 py-2 font-medium text-white hover:bg-slate-700"
      >
        Sign in
      </a>
    </div>
  )
}
