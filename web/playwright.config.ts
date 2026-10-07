import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests', fullyParallel: false, workers: 1, timeout: 30000,
  use: {
    baseURL: 'http://127.0.0.1:5173', viewport: { width: 1440, height: 1050 },
    trace: 'retain-on-failure',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {},
  },
  webServer: [
    { command: 'uv run --project .. agentcommons serve --port 8000', url: 'http://127.0.0.1:8000/api/health', reuseExistingServer: false,
      env: { AGENTCOMMONS_ADMIN_TOKEN: 'browser-test-only-token-not-a-secret', AGENTCOMMONS_DB: `/tmp/agentcommons-browser-${process.pid}.db` } },
    { command: 'npm run dev -- --port 5173', url: 'http://127.0.0.1:5173', reuseExistingServer: false },
  ],
})
