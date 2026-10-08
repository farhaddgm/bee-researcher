import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';

const baseUrl = process.env.BEE_ADMIN_URL || 'http://127.0.0.1:8010/admin';
const requestedLocale = process.env.BEE_ADMIN_LOCALE || 'en';
const username = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME;
const password = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if (!username || !password) throw new Error('Admin bootstrap credentials are not available.');
const root = process.env.CAPTURE_OUTPUT || '/captures';
const runDir = path.join(root, new Date().toISOString().replace(/[:.]/g, '-'));
await fs.mkdir(runDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, locale: 'en-US' });
page.setDefaultTimeout(8000);
page.on('dialog', d => d.dismiss());
const slug = x => String(x).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 90) || 'state';
const waitUi = async () => { await page.waitForTimeout(500); await page.evaluate(() => document.fonts?.ready); await page.waitForTimeout(200); };
const captured = [];
async function shot(view, label, n) {
  await waitUi();
  const stem = `${String(n).padStart(2, '0')}-${slug(view)}-${slug(label)}`;
  const png = path.join(runDir, `${stem}.png`);
  await page.screenshot({ path: png, fullPage: true });
  await fs.writeFile(path.join(runDir, `${stem}.html`), '<!doctype html>\n' + await page.content(), 'utf8');
  captured.push({ view, label, png, html: png.replace(/\.png$/, '.html') });
}
async function closeOverlay() {
  const accountDialog = page.locator('dialog.accounts-dialog[open]');
  if (await accountDialog.count()) {
    await accountDialog.getByRole('button', { name: /^(cancel|انصراف)$/i }).click();
    await accountDialog.waitFor({ state: 'hidden' });
  }
  const close = page.locator('.modal-backdrop:visible .modal-close, .modal-backdrop:visible button').filter({ hasText: /^(×|cancel|close|انصراف|بستن)$/i }).first();
  if (await close.isVisible().catch(() => false)) await close.click();
  const drawer = page.locator('#closeDrawer:visible').first();
  if (await drawer.isVisible().catch(() => false)) await drawer.click({ force: true }).catch(() => {});
  await waitUi();
}
async function nav(view) {
  if (view === 'account') {
    await page.locator('#sidebarAccountTrigger').click();
    await page.locator('#sidebarAccountMenu [data-account-action="account"]').click();
  } else {
    await page.locator(`.nav-btn[data-view="${view}"]`).first().click();
  }
  await waitUi();
}
async function openSelector(view, selector, label, n, expectedSelector = '#modalRoot:not(.hidden) .modal-backdrop') {
  await nav(view);
  const target = page.locator(selector).first();
  if (!(await target.isVisible().catch(() => false))) {
    throw new Error(`Required action ${selector} is not visible in ${view}.`);
  }
  await target.click();
  try {
    await page.locator(expectedSelector).first().waitFor({ state: 'visible' });
  } catch (error) {
    // Preserve a compact, non-sensitive state snapshot in CI logs.  A modal
    // can be inserted into the DOM but remain invisible if an old cleanup
    // layer immediately closes it; reporting this distinction turns a vague
    // "button did nothing" failure into an actionable regression.
    const diagnostic = await page.evaluate(() => {
      const root = document.getElementById('modalRoot');
      const app = document.getElementById('app');
      const backdrop = root?.querySelector('.modal-backdrop');
      const style = root ? getComputedStyle(root) : null;
      return {
        rootClass: root?.className || null,
        rootChildren: root?.childElementCount || 0,
        rootDisplay: style?.display || null,
        rootVisibility: style?.visibility || null,
        backdropPresent: Boolean(backdrop),
        backdropDisplay: backdrop ? getComputedStyle(backdrop).display : null,
        appClass: app?.className || null,
        appVisibility: app ? getComputedStyle(app).visibility : null,
        activeElement: document.activeElement?.id || document.activeElement?.tagName || null,
      };
    });
    throw new Error(`Required action ${selector} did not reveal ${expectedSelector}: ${JSON.stringify(diagnostic)}; ${error.message}`);
  }
  await shot(view, label, n);
  await closeOverlay();
  return true;
}

await page.goto(new URL("/admin/login-up",baseUrl).href, { waitUntil: 'domcontentloaded', timeout: 30000 });
await waitUi();
await page.locator('#loginUser').fill(username);
await page.locator('#loginPass').fill(password);
await page.locator('#loginForm button[type="submit"], #loginSubmit').click();
await page.locator('#app:not(.hidden)').waitFor({ state: 'visible' });
await page.evaluate(locale => typeof setLanguage === 'function' && setLanguage(locale), requestedLocale);
await waitUi();
let n = 1;
await openSelector('assistants', '#newAssistantBtn', 'create-assistant', n++);
await openSelector('assistants', '#quickAssistantBtn', 'quick-setup', n++);
await openSelector('businesses', '#newBusinessBtn', 'add-business', n++);
await openSelector('sources', '#addSourceBtn', 'add-media', n++, '#modalRoot:not(.hidden) #mediaDraftName');
await openSelector('sources', '#sourceSuggestionBtn', 'suggest-media', n++);
await openSelector('topics', '#addTopicBtn', 'add-topic', n++, '#modalRoot:not(.hidden) #draftTopicName');
await openSelector('schedule', '#channelSettingsCard [data-edit-telegram]', 'telegram-settings', n++);
// Account management now uses the email/Google access directory. The hidden
// legacy password-user button must not be treated as the supported UI action.
await openSelector('account', '#accountsPanel .accounts-head .btn.primary', 'add-user', n++, 'dialog.accounts-dialog[open]');
await fs.writeFile(path.join(runDir, 'manifest.json'), JSON.stringify({ createdAt: new Date().toISOString(), screenshots: captured }, null, 2));
await browser.close();
console.log(JSON.stringify({ runDir, locale: requestedLocale, count: captured.length }, null, 2));
