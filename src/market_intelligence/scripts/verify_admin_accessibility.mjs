import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';

// Real authenticated DOM, not snapshots or mocked markup. Never run fixtures
// against production; this is an automated gate, not human WCAG certification.
const base = process.env.BEE_ADMIN_URL;
const username = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME;
const password = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if (!base || !username || !password || process.env.MARKET_INTELLIGENCE_ENVIRONMENT !== 'test') {
  throw new Error('Accessibility E2E requires an isolated test application and credentials.');
}
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
try {
  await page.goto(new URL('/admin/login-up', base).href);
  await page.locator('#loginUser').fill(username);
  await page.locator('#loginPass').fill(password);
  await page.locator('#loginSubmit').click();
  await page.locator('#app:not(.hidden)').waitFor();
  const meta = await context.request.get(new URL('/meta', base).href);
  assert.equal((await meta.json()).environment, 'test', 'Refusing production fixtures');
  await page.waitForFunction(() => state.runtimeSettings?.assistant_id === state.assistantId);
  await page.evaluate(() => {
    window.setLanguage('en');
    document.documentElement.dataset.theme = 'honey';
  });
  const views = ['assistants', 'overview', 'publications', 'feedback', 'businesses', 'sources', 'topics', 'schedule', 'content', 'settings', 'operations', 'support'];
  const results = [];
  for (const view of views) {
    await page.evaluate(view => window.setView(view), view);
    await page.waitForTimeout(180);
    const audit = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
    results.push({ view, violations: audit.violations.map(v => ({
      id: v.id, impact: v.impact, targets: v.nodes.map(n => n.target),
    })) });
  }
  const output = process.env.CAPTURE_OUTPUT;
  if (output) {
    await fs.mkdir(output, { recursive: true });
    await fs.writeFile(path.join(output, 'admin-accessibility.json'), JSON.stringify({
      scope: 'Automated WCAG 2.1 AA, 12 authenticated default-theme views; no human screen-reader certification', results,
    }, null, 2));
  }
  assert.deepEqual(errors, [], 'Browser runtime errors');
  assert.deepEqual(results.filter(r => r.violations.length), [], 'Automated accessibility regressions');
  console.log('Accessibility E2E passed: all 12 authenticated admin views; WCAG 2.1 AA automated rules.');
} finally {
  await browser.close();
}
