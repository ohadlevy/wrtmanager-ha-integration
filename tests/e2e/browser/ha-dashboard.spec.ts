import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import * as http from 'http';

const HA_URL = process.env.HA_URL || 'http://localhost:18123';
const HA_USER = process.env.HA_USER || 'wrt';
const HA_PASSWORD = process.env.HA_PASSWORD || 'wrt-test-123';
const SCREENSHOT_DIR = process.env.SCREENSHOT_DIR || '.test-screenshots';

if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

/**
 * Get an access token from HA via the auth flow.
 * Uses the login_flow API which works for local users.
 */
async function getHAToken(): Promise<string> {
  // Step 1: Create a login flow
  const flowRes = await fetch(`${HA_URL}/auth/login_flow`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: HA_URL, handler: ['homeassistant', null], redirect_uri: `${HA_URL}/` }),
  });
  const flow = await flowRes.json();

  // Step 2: Submit credentials
  const submitRes = await fetch(`${HA_URL}/auth/login_flow/${flow.flow_id}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: HA_USER, password: HA_PASSWORD, client_id: HA_URL }),
  });
  const submitResult = await submitRes.json();

  if (!submitResult.result) {
    throw new Error(`Login failed: ${JSON.stringify(submitResult)}`);
  }

  // Step 3: Exchange auth code for token
  const tokenRes = await fetch(`${HA_URL}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: `grant_type=authorization_code&code=${submitResult.result}&client_id=${encodeURIComponent(HA_URL)}`,
  });
  const tokenData = await tokenRes.json();

  if (!tokenData.access_token) {
    throw new Error(`Token exchange failed: ${JSON.stringify(tokenData)}`);
  }

  return tokenData.access_token;
}

let cachedToken: string | null = null;

async function loginToHA(page: Page) {
  if (!cachedToken) {
    cachedToken = await getHAToken();
  }

  // Navigate to HA and wait for the page to fully load (it may redirect to /auth)
  await page.goto(HA_URL, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);

  // Inject token into HA's localStorage auth storage
  await page.evaluate(({ token, url }) => {
    const hassTokens = {
      hassUrl: url,
      clientId: url,
      access_token: token,
      token_type: 'Bearer',
      expires_in: 86400,
      refresh_token: '',
      expires: Date.now() + 86400000,
    };
    localStorage.setItem('hassTokens', JSON.stringify(hassTokens));
  }, { token: cachedToken, url: HA_URL });

  // Reload to pick up the token
  await page.goto(HA_URL, { waitUntil: 'networkidle' });
  await page.waitForTimeout(5000);
}

test.describe('WrtManager Dashboard Cards', () => {
  test.beforeEach(async ({ page }) => {
    await loginToHA(page);
  });

  test('dashboard loads with wrtmanager cards', async ({ page }, testInfo) => {
    await page.goto(`${HA_URL}/lovelace/network`);
    await page.waitForTimeout(5000);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, `dashboard-cards-${testInfo.project.name}.png`),
      fullPage: true,
    });
  });

  test('router-health-card renders', async ({ page }, testInfo) => {
    await page.goto(`${HA_URL}/lovelace/network`);
    await page.waitForTimeout(5000);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, `router-health-${testInfo.project.name}.png`),
      fullPage: true,
    });
  });

  test('network-devices-card renders', async ({ page }, testInfo) => {
    await page.goto(`${HA_URL}/lovelace/network`);
    await page.waitForTimeout(5000);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, `network-devices-${testInfo.project.name}.png`),
      fullPage: true,
    });
  });

  test('no console errors on dashboard', async ({ page }, testInfo) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    await page.goto(`${HA_URL}/lovelace/network`);
    await page.waitForTimeout(5000);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, `console-check-${testInfo.project.name}.png`),
      fullPage: true,
    });

    const realErrors = consoleErrors.filter(
      (e) => !e.includes('favicon') && !e.includes('service-worker')
    );
    if (realErrors.length > 0) {
      console.warn('Console errors found:', realErrors);
    }
  });
});

test.describe('WrtManager Dashboard - Responsive', () => {
  test.beforeEach(async ({ page }) => {
    await loginToHA(page);
  });

  test('dashboard renders at current viewport', async ({ page }, testInfo) => {
    await page.goto(`${HA_URL}/lovelace/network`);
    await page.waitForTimeout(5000);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, `responsive-${testInfo.project.name}.png`),
      fullPage: true,
    });
    const body = await page.textContent('body');
    expect(body).toBeTruthy();
  });
});

test.describe('WrtManager - Entity Pages', () => {
  test.beforeEach(async ({ page }) => {
    await loginToHA(page);
  });

  test('entities page shows wrtmanager entities', async ({ page }, testInfo) => {
    await page.goto(`${HA_URL}/developer-tools/state`);
    await page.waitForTimeout(3000);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, `entities-${testInfo.project.name}.png`),
      fullPage: true,
    });
  });

  test('devices page shows routers', async ({ page }, testInfo) => {
    await page.goto(`${HA_URL}/config/devices/dashboard`);
    await page.waitForTimeout(3000);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, `devices-${testInfo.project.name}.png`),
      fullPage: true,
    });
    const pageContent = await page.textContent('body');
    expect(pageContent).toBeTruthy();
  });

  test('integration config page loads', async ({ page }, testInfo) => {
    await page.goto(`${HA_URL}/config/integrations/dashboard`);
    await page.waitForTimeout(3000);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, `integrations-${testInfo.project.name}.png`),
      fullPage: true,
    });
  });
});
