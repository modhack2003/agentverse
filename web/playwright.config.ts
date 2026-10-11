import { defineConfig } from '@playwright/test'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

export default defineConfig({
  testDir: './tests', fullyParallel: false, workers: 1, timeout: 30000,
  use: {
    baseURL: 'http://127.0.0.1:5173', viewport: { width: 1440, height: 1050 },
    trace: 'retain-on-failure',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {},
  },
  webServer: [
    { command: 'uv run --project .. python ../tests/onboarding_server.py', url: 'http://127.0.0.1:8100/api/health', reuseExistingServer: false },
    { command: 'uv run --project .. agentverse serve --port 8000', url: 'http://127.0.0.1:8000/api/health', reuseExistingServer: false,
      env: { AGENTVERSE_ADMIN_TOKEN: 'browser-test-only-token-not-a-secret', AGENTVERSE_ADMIN_USERNAME: 'audit-ui-admin', AGENTVERSE_ADMIN_PASSWORD: 'audit-ui-password', AGENTVERSE_DB: join(tmpdir(), `agentverse-browser-${process.pid}-${Date.now()}.db`) } },
    { command: 'npm run dev -- --port 5173 --host 127.0.0.1', url: 'http://127.0.0.1:5173', reuseExistingServer: false },
  ],
})
