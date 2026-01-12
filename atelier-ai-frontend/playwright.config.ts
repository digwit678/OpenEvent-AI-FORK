import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E configuration for OpenEvent-AI frontend.
 *
 * Prerequisites:
 * - Backend running on http://localhost:8000
 * - Frontend running on http://localhost:3000
 *
 * Run tests:
 *   cd atelier-ai-frontend && npx playwright test
 *
 * Run specific test:
 *   npx playwright test e2e/hybrid-qna.spec.ts
 *
 * Run with UI:
 *   npx playwright test --ui
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // Run sequentially for workflow tests
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // Single worker for sequential workflow tests
  reporter: 'html',

  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Expect backend and frontend to be running
  webServer: [
    {
      command: 'echo "Expecting backend on :8000"',
      url: 'http://localhost:8000/api/workflow/health',
      reuseExistingServer: true,
      timeout: 5000,
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:3000',
      reuseExistingServer: true,
      timeout: 30000,
    },
  ],
});
