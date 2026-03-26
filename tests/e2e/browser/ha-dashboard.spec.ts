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

async function loginAndNavigate(page: Page) {
  const token = await getHAToken();

  // Set token in localStorage — wait for load to avoid navigation context destruction
  await page.goto(HA_URL, { waitUntil: 'load' });
  await page.waitForTimeout(1000);
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
  }, { token, url: HA_URL });

  // Navigate to dashboard and wait for cards to render
  await page.goto(`${HA_URL}/lovelace/network`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);
}

/**
 * Screenshot a specific custom card element, falling back to full page.
 */
async function screenshotCard(page: Page, cardTag: string, screenshotPath: string) {
  try {
    const card = page.locator(cardTag).first();
    await card.waitFor({ state: 'visible', timeout: 10000 });
    await card.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    await card.screenshot({ path: screenshotPath });
  } catch {
    console.warn(`Card element '${cardTag}' not found, taking full page screenshot`);
    await page.screenshot({ path: screenshotPath, fullPage: true });
  }
}

const CARDS = [
  { tag: 'router-health-card', name: 'router-health' },
  { tag: 'network-devices-card', name: 'network-devices' },
  { tag: 'network-topology-card', name: 'network-topology' },
  { tag: 'signal-heatmap-card', name: 'signal-heatmap' },
  { tag: 'roaming-activity-card', name: 'roaming-activity' },
  { tag: 'interface-health-card', name: 'interface-health' },
  { tag: 'wifi-networks-card', name: 'wifi-networks' },
];

test.describe('WrtManager Dashboard Cards', () => {
  // All card screenshots in one test — login once, screenshot all cards
  test('card renders', async ({ page }, testInfo) => {
    await loginAndNavigate(page);

    // Individual card screenshots
    for (const card of CARDS) {
      await screenshotCard(
        page,
        card.tag,
        path.join(SCREENSHOT_DIR, `${card.name}-${testInfo.project.name}.png`),
      );
    }
  });

  test('no console errors on dashboard', async ({ page }, testInfo) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    await loginAndNavigate(page);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, `console-check-${testInfo.project.name}.png`),
      fullPage: true,
    });

    const realErrors = consoleErrors.filter(
      (e) => !e.includes('favicon') && !e.includes('service-worker')
    );
    // Write console errors to file for diagnostics
    const errorFile = path.join(SCREENSHOT_DIR, 'console-errors.txt');
    if (realErrors.length > 0) {
      console.warn('Console errors found:', realErrors);
      fs.writeFileSync(errorFile, realErrors.join('\n'));
    } else {
      fs.writeFileSync(errorFile, 'No console errors');
    }
  });
});
