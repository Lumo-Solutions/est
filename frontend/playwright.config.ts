import { defineConfig, devices } from '@playwright/test'

// Uses the machine's already-installed Chrome -- `npx playwright install` is
// never run for this project (standing instruction: don't download browsers).
export default defineConfig({
  testDir: './e2e',
  // e2e/real-backend/** needs the real dev stack, one worker at a time, and its
  // own config (playwright.real-backend.config.ts, `npm run e2e:real-backend`).
  // Picked up here it ran ~80 real-login specs on 6 parallel workers against the
  // shared stack and failed en masse (TOTP replay protection, Keycloak brute-force).
  testIgnore: ['**/real-backend/**'],
  fullyParallel: true,
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 30_000,
  },
  use: {
    baseURL: 'http://localhost:5173',
  },
  projects: [
    {
      name: 'chrome',
      use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    },
  ],
})
