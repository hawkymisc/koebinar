import { defineConfig, devices } from '@playwright/test'

const apiPort = 18002
const webPort = 15175
const repositoryRoot = new URL('..', import.meta.url).pathname

export default defineConfig({
  testDir: './tests/browser',
  fullyParallel: false,
  workers: 1,
  timeout: 240_000,
  expect: { timeout: 30_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  outputDir: 'test-results',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: `http://127.0.0.1:${webPort}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'on',
  },
  webServer: [
    {
      command: `${repositoryRoot}/.venv/bin/python tests/browser/e2e_api.py --port ${apiPort}`,
      cwd: repositoryRoot,
      url: `http://127.0.0.1:${apiPort}/api/v1/health`,
      timeout: 30_000,
      reuseExistingServer: false,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${webPort}`,
      cwd: new URL('.', import.meta.url).pathname,
      env: {
        ...process.env,
        VITE_API_BASE: `http://127.0.0.1:${apiPort}/api/v1`,
      },
      url: `http://127.0.0.1:${webPort}`,
      timeout: 30_000,
      reuseExistingServer: false,
    },
  ],
})
