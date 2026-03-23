import { defineConfig, devices } from '@playwright/test';

const HA_URL = process.env.HA_URL || 'http://localhost:18123';
const SCREENSHOT_DIR = process.env.SCREENSHOT_DIR || '.test-screenshots';

export default defineConfig({
  testDir: '.',
  timeout: 60000,
  retries: 1,
  use: {
    baseURL: HA_URL,
    screenshot: 'on',
    trace: 'on-first-retry',
  },
  outputDir: SCREENSHOT_DIR,
  projects: [
    {
      name: 'desktop',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1920, height: 1080 },
      },
    },
    {
      name: 'mobile',
      use: {
        ...devices['iPhone 14'],
      },
    },
    {
      name: 'tablet',
      use: {
        ...devices['iPad (gen 7)'],
      },
    },
  ],
});
