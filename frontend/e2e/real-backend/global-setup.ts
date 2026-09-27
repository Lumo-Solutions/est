import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(__dirname, '../../../')

// Demo users these specs log in as through the real Keycloak form. Each is
// seeded by deploy/keycloak/bootstrap.sh with CONFIGURE_TOTP + a temporary
// password (`make bootstrap-keycloak`) -- dev-prep-login-users.sh clears
// that so the interactive login here doesn't also have to automate TOTP
// enrolment, exactly like dev-token.sh already does for a single user
// before a scripted password-grant request. See docs/keycloak-setup.md's
// "Interactive browser login in dev" section for the human first-login
// flow (TOTP included) that this intentionally bypasses.
//
// md1 is deliberately NOT in this list: settlement.spec.ts's approve step
// needs a real MFA step-up (app/security/deps.py::require_mfa_step_up,
// acr=silver), which needs an actual TOTP credential -- see
// dev-reset-totp-user.sh and totp.ts below.
const DEMO_USERS: Record<string, string> = {
  estimator1: 'Estimator1Pass!',
  lead1: 'Lead1Pass!',
  bd1: 'Bd1Pass!',
}

export const MD1_PASSWORD = 'Md1Pass!'

function loadDotEnv(file: string): Record<string, string> {
  const out: Record<string, string> = {}
  let text: string
  try {
    text = readFileSync(file, 'utf-8')
  } catch {
    return out
  }
  for (const line of text.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const eq = trimmed.indexOf('=')
    if (eq === -1) continue
    out[trimmed.slice(0, eq)] = trimmed.slice(eq + 1)
  }
  return out
}

export default async function globalSetup(): Promise<void> {
  const env = { ...process.env, ...loadDotEnv(path.join(REPO_ROOT, 'deploy', '.env')) }

  const userArgs = Object.entries(DEMO_USERS).map(([user, pass]) => `${user}:${pass}`)
  execFileSync('bash', ['deploy/keycloak/dev-prep-login-users.sh', ...userArgs], {
    cwd: REPO_ROOT,
    env,
    stdio: 'inherit',
  })
  execFileSync('bash', ['deploy/keycloak/dev-reset-totp-user.sh', 'md1', MD1_PASSWORD], {
    cwd: REPO_ROOT,
    env,
    stdio: 'inherit',
  })

  // Idempotent -- builds/reuses the D1-SIM project (BOQ line + a vendor
  // with an ACCEPTED quotation line item) these specs drive settlement and
  // procurement actions against, without depending on manual setup or an
  // earlier `make dev-simulate-settlement` run. See app/cli.py::simulate_settlement.
  //
  // Only the project/BOQ/vendor/accepted-quote setup at the START of that
  // CLI command is load-bearing here -- everything these specs actually
  // exercise happens through the UI/API themselves. On a long-lived dev
  // database, other `make dev-simulate-*` targets (e.g. semantic-matching)
  // can leave OTHER unrelated BOQ lines in this same D1-SIM project with a
  // quantity but no accepted quote, which makes this CLI command's own
  // later submit() step fail with "every line needs a resolved cost" --
  // settlement.spec.ts's resolveUnresolvedLines() (helpers.ts) handles
  // that for the settlement THESE specs build, so a failure here is
  // swallowed rather than aborting the whole run over state this step
  // doesn't actually need to have succeeded.
  try {
    execFileSync('bash', ['-lc', 'make dev-simulate-settlement'], {
      cwd: REPO_ROOT,
      env,
      stdio: 'inherit',
    })
  } catch (err) {
    console.warn(
      '[global-setup] make dev-simulate-settlement did not complete (see output above) -- ' +
        'continuing anyway, since the D1-SIM project/BOQ/accepted-quote fixture it needs is set up ' +
        'before the step that can fail this way. If a spec then fails to find that fixture, run ' +
        '`make dev-simulate-settlement` by hand to see the real error.',
      err instanceof Error ? err.message : err,
    )
  }
}
