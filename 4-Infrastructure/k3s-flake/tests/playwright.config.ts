import { defineConfig } from '@playwright/test';

/**
 * Playwright config for Research Stack end-to-end routing tests.
 *
 * Tests the full traffic path:
 *   Internet → Edge Caddy (TLS) → Traefik Ingress → k3s services
 *
 * Run against live infrastructure:
 *   npx playwright test
 *
 * Run against a specific base URL (e.g. local sim):
 *   BASE_URL=http://localhost:8080 npx playwright test
 */
export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  timeout: 30_000,
  retries: 1,
  use: {
    baseURL: process.env.BASE_URL || 'https://researchstack.info',
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: {
      'User-Agent': 'ResearchStack-Playwright-E2E/1.0',
    },
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'test-results' }],
  ],
});
