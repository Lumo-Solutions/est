import { loginUrl } from '../lib/api'

// Public page (no auth gate, no /auth/me call): where Keycloak's end-session
// redirect lands after sign-out (backend auth.py SIGNED_OUT_PATH, registered
// as a post-logout redirect URI on the client). "Sign in" starts a fresh
// login; because the SSO session was ended, Keycloak asks for credentials.
export function SignedOutPage() {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-4 bg-canvas">
      <h1 className="text-page-title font-semibold text-ink-title">You have been signed out</h1>
      <p className="text-base text-muted">Your session has ended. Sign in again to continue.</p>
      <a
        href={loginUrl('/')}
        className="rounded-control bg-brand px-6 py-2.5 text-base font-medium text-white transition-colors duration-150 hover:bg-brand-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
      >
        Sign in
      </a>
    </div>
  )
}
