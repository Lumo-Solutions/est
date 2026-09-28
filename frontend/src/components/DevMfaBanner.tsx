// Shown across the top of the app shell whenever the backend reports
// DEV_DISABLE_MFA is active (GET /auth/me -> mfa_disabled_dev, only ever true
// in dev/test). A persistent reminder that this environment has no login OTP
// and no step-up -- never something to see anywhere real.
export function DevMfaBanner({ active }: { active: boolean }) {
  if (!active) return null
  return (
    <div
      role="status"
      data-testid="dev-mfa-banner"
      className="shrink-0 border-b border-amber-300 bg-warning-subtle px-4 py-1 text-center text-xs font-semibold text-amber-800"
    >
      DEV: MFA disabled
    </div>
  )
}
