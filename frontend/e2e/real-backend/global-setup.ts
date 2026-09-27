import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(__dirname, '../../../')

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

  // Idempotent (see deploy/keycloak/bootstrap.sh) -- ensures the demo
  // users, their dev-fixed TOTP secrets (totp.ts's DEMO_TOTP_SECRETS,
  // guarded there by APP_ENV), the auth_time claim mapper, and the
  // browser-stepup authentication flow (fix/keycloak-step-up) all exist,
  // regardless of whether a human already ran `make bootstrap-keycloak`
  // for this stack.
  execFileSync('bash', ['-lc', 'make bootstrap-keycloak'], {
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
