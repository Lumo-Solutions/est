import { defineConfig, devices } from '@playwright/test'

// Uses the machine's already-installed Chrome -- `npx playwright install` is
// never run for this project (standing instruction: don't download browsers).
export default defineConfig({
  testDir: './e2e',
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
