import { defineConfig, devices } from '@playwright/test'

// Separate from playwright.config.ts on purpose: those smoke tests mock
// /auth/me and run against `npm run dev` (no backend at all). These drive
// the REAL dev stack (`make up`) end to end -- real Keycloak login, real
// Postgres, real approval routing -- so they need it already running and
// reachable at caddy-dev's HTTPS origin (deploy/docker-compose.override.dev.yml
// / deploy/caddy/Caddyfile.dev), not Vite's dev server. No `webServer` here:
// unlike the smoke config, there is nothing for Playwright itself to start.
// ignoreHTTPSErrors: caddy-dev uses `tls internal` (a locally-generated,
// self-signed cert) -- see docs/keycloak-setup.md's "Interactive browser
// login in dev" section for why that's the fix and how a human trusts the
// same cert once for a real Chrome profile.
export default defineConfig({
  testDir: './e2e/real-backend',
  // step-up-freshness.spec.ts (fix/keycloak-step-up) only proves anything
  // once Keycloak's Level 2 loa-max-age and the backend's
  // STEP_UP_MAX_AGE_S have both been lowered to a short test-only window --
  // at this config's real 300s default its two "wait past max age" pauses
  // alone take over ten minutes and still assert nothing that isn't
  // already re-proven at a smaller scale in that setup. Run it via
  // deploy/keycloak/test-stepup-freshness.sh (playwright.step-up-freshness.config.ts)
  // instead, never as part of a normal `npm run e2e:real-backend`.
  testIgnore: ['**/step-up-freshness.spec.ts'],
  fullyParallel: false,
  workers: 1,
  // Generous: settlement.spec.ts's TOTP enrolment + MFA step-up
  // (helpers.ts's submitTotpCode) can each need one ~65s wait if the first
  // generated code straddles Keycloak's 30s step boundary, to ride out its
  // brute-force "quick login check" penalty rather than retrying into it.
  timeout: 180_000,
  globalSetup: './e2e/real-backend/global-setup.ts',
  use: {
    baseURL: 'https://localhost:8443',
    ignoreHTTPSErrors: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chrome',
      use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    },
  ],
})
