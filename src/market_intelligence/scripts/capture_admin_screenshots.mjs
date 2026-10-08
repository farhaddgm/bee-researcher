import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';

const baseUrl = process.env.BEE_ADMIN_URL || 'http://127.0.0.1:8010/admin';
const username = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME;
const password = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if (!username || !password) throw new Error('Admin bootstrap credentials are not available in the environment.');

const outputRoot = process.env.CAPTURE_OUTPUT || '/captures';
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const runDir = path.join(outputRoot, stamp);
await fs.mkdir(runDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
  locale: 'en-US',
  colorScheme: 'light',
});
const page = await context.newPage();
page.setDefaultTimeout(12000);
page.on('dialog', async dialog => { await dialog.dismiss(); });

const slug = value => String(value || 'state').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80) || 'state';
const waitForUi = async () => {
  await page.waitForTimeout(450);
  await page.evaluate(() => document.fonts?.ready);
  await page.waitForTimeout(150);
};
const safeName = (view, label, index = 0) => `${String(index + 1).padStart(2, '0')}-${slug(view)}-${slug(label)}`;
const capture = async (view, label, index = 0) => {
  await waitForUi();
  const file = path.join(runDir, `${safeName(view, label, index)}.png`);
  await page.screenshot({ path: file, fullPage: true });
  const htmlFile = file.replace(/\.png$/, '.html');
  await fs.writeFile(htmlFile, '<!doctype html>\n' + await page.content(), 'utf8');
  return { view, label, png: file, html: htmlFile, url: page.url() };
};

const results = [];
// The admin shell keeps a few background requests open, so networkidle is
// intentionally not used here. DOM readiness plus the explicit UI wait is a
// more reliable capture boundary.
await page.goto(new URL("/admin/login-up",baseUrl).href, { waitUntil: 'domcontentloaded', timeout: 30000 });
await waitForUi();
await page.locator('#loginUser').fill(username);
await page.locator('#loginPass').fill(password);
await page.locator('#loginForm button[type="submit"], #loginSubmit').click();
await page.locator('#app:not(.hidden)').waitFor({ state: 'visible' });
await page.evaluate(() => { if (typeof setLanguage === 'function') setLanguage('en'); });
await waitForUi();
results.push(await capture('shell', 'assistants-default'));

// Capture every visible navigation view. Navigation is read-only; destructive
// actions (delete, revoke, run, publish, activate, save) are never clicked.
const navs = await page.locator('.nav-btn[data-view]:not(.hidden)').evaluateAll(nodes => nodes.map(n => ({ view: n.dataset.view, label: n.innerText.trim() })));
for (const nav of navs) {
  const button = page.locator(`.nav-btn[data-view="${nav.view}"]`).first();
  if (!(await button.isVisible().catch(() => false))) continue;
  await button.click();
  await waitForUi();
  results.push(await capture(nav.view, 'default'));

  // Safe open states: these buttons only reveal a form, modal, drawer or
  // details panel. They do not submit data. Keep this allow-list explicit.
  const safePatterns = /^(create assistant|add media|add topic|edit|edit information|edit bot and channels|edit content|readiness check|suggest a media source|add user|view|details|open workspace)$/i;
  const buttons = await page.locator(`#view-${nav.view} button:visible`).evaluateAll(nodes => {
    const seen = new Set();
    return nodes.map((n, i) => ({ i, text: n.innerText.trim(), id: n.id, title: n.getAttribute('aria-label') || '' }))
      .filter(x => { const key = x.text || x.title; if (!key || seen.has(key)) return false; seen.add(key); return true; })
      .slice(0, 8);
  });
  let stateIndex = 0;
  for (const candidate of buttons) {
    const label = candidate.text || candidate.title;
    if (!safePatterns.test(label)) continue;
    const target = page.locator(`#view-${nav.view} button:visible`).filter({ hasText: candidate.text }).first();
    if (!(await target.isVisible().catch(() => false))) continue;
    try {
      await target.click();
      await waitForUi();
      const overlayVisible = await page.locator('.modal-backdrop:visible, .drawer.open:visible, .account-security-panel:visible').count();
      if (overlayVisible || candidate.text.toLowerCase().includes('edit') || candidate.text.toLowerCase().includes('add') || candidate.text.toLowerCase().includes('readiness') || candidate.text.toLowerCase().includes('open')) {
        results.push(await capture(nav.view, `open-${label}`, stateIndex++));
      }
      // Close only via explicit close/cancel controls; no form submission.
      const close = page.locator('.modal-backdrop:visible .modal-close, .modal-backdrop:visible button').filter({ hasText: /^(×|cancel|close|انصراف|بستن)$/i }).first();
      if (await close.isVisible().catch(() => false)) await close.click();
      const drawerClose = page.locator('#closeDrawer:visible').first();
      if (await drawerClose.isVisible().catch(() => false)) await drawerClose.click();
      await waitForUi();
    } catch { /* one unavailable state must not stop the inventory */ }
  }
}

await fs.writeFile(path.join(runDir, 'manifest.json'), JSON.stringify({ createdAt: new Date().toISOString(), baseUrl, viewport: { width: 1920, height: 1080 }, screenshots: results }, null, 2));
await browser.close();
console.log(JSON.stringify({ runDir, count: results.length, screenshots: results }, null, 2));
