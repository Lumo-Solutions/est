import { defineConfig, devices } from '@playwright/test'

// Dedicated config for e2e/real-backend/step-up-freshness.spec.ts ONLY
// (fix/keycloak-step-up review item 3). Deliberately separate from
// playwright.real-backend.config.ts, which testIgnores this one file: that
// config's normal run happens against the real 300s STEP_UP_MAX_AGE_S/
// loa-max-age, where this spec's two "wait past max age" pauses alone would
// take over ten minutes per run and still only re-prove at a larger scale
// what a short window already proves. Only meaningful invoked via
// deploy/keycloak/test-stepup-freshness.sh, which lowers both settings to a
// short test-only window first and restores them afterwards regardless of
// outcome.
export default defineConfig({
  testDir: './e2e/real-backend',
  testMatch: 'step-up-freshness.spec.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 600_000,
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
