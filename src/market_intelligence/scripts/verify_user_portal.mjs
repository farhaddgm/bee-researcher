import { chromium } from 'playwright';

const baseUrl = process.env.BEE_USER_URL || 'http://127.0.0.1:8010/user';
const username = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME;
const password = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if (!username || !password) throw new Error('Isolated User-service E2E credentials are required.');

const browser = await chromium.launch({ headless: true });
try {
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
await context.grantPermissions(['notifications'], { origin: new URL(baseUrl).origin });
await context.addInitScript(() => {
  window.__beeE2ENotifications = [];
  class TestNotification {
    constructor(title, options = {}) { window.__beeE2ENotifications.push({ title, body: options.body || '' }); }
    static get permission() { return 'granted'; }
    static requestPermission() { return Promise.resolve('granted'); }
  }
  Object.defineProperty(window, 'Notification', { configurable: true, value: TestNotification });
});

const page = await context.newPage();
page.setDefaultTimeout(12_000);
const errors = [];
page.on('pageerror', error => errors.push(error.message));

await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30_000 });
await page.locator('#login:not(.hidden)').waitFor({ state: 'visible' });
await page.locator('#username').fill(username);
await page.locator('#password').fill(password);
await page.locator('#loginButton').click();
await page.locator('#app:not(.hidden)').waitFor({ state: 'visible' });
const who = await page.locator('#sidebarUserName').textContent();
if (who?.trim() !== username) throw new Error(`User identity did not render in the account menu: ${who}`);

// Verify a real session can move between the separate reader and settings
// pages, and that the notification preference is persisted through the API.
await page.goto(new URL('/user/settings', baseUrl).toString(), { waitUntil: 'domcontentloaded' });
await page.locator('#app:not(.hidden)').waitFor({ state: 'visible' });
const notificationToggle = page.locator('#notificationToggle');
const notificationLabel = page.locator('label.switch[aria-label="Browser notifications"]');
if (!(await notificationToggle.isChecked())) await notificationLabel.click();
if (!(await notificationToggle.isChecked())) throw new Error('The browser-notification switch did not toggle on through its visible track.');
await page.locator('#directionSelect').selectOption('rtl');
await page.locator('#saveSettingsButton').click();
await page.getByText('Saved just now.', { exact: true }).waitFor({ state: 'visible' });
const savedPreferences = await page.evaluate(async () => {
  const response = await fetch('/user/api/preferences', { credentials: 'same-origin' });
  if (!response.ok) throw new Error(`Preferences returned ${response.status}`);
  return response.json();
});
if (savedPreferences.notifications !== true) throw new Error('Browser notification preference was not persisted.');
if (savedPreferences.text_direction !== 'rtl') throw new Error('News-card text direction preference was not persisted.');

const baselineId = '11111111-1111-4111-8111-111111111111';
const newId = '22222222-2222-4222-8222-222222222222';
const readerFixtureAssistantId = '33333333-3333-4333-8333-333333333333';
let publications = [{
  id: baselineId,
  message_text: 'E2E baseline publication',
  source_name: 'Browser test source',
  published_at: new Date().toISOString(),
  created_at: new Date().toISOString(),
  relevance_score: 0.8,
}];
// Keep the browser test deterministic even in a pristine CI database with no
// provisioned project. The access-control boundary itself is tested against
// real workspaces by the Admin support E2E; this fixture isolates reader
// notifications and article-dialog behavior from environment setup.
await page.route('**/user/api/assistants', route => route.fulfill({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify({ count: 1, assistants: [{
    id: readerFixtureAssistantId,
    slug: 'reader-e2e-fixture',
    name: 'Reader E2E fixture',
    business_name: 'Browser tests',
    status: 'active',
  }] }),
}));
await page.route('**/user/api/assistants/*/publications*', route => route.fulfill({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify({ count: publications.length, publications }),
}));
await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
await page.locator('#app:not(.hidden)').waitFor({ state: 'visible' });
await page.locator(`.news-card[data-news-id="${baselineId}"]`).waitFor({ state: 'visible' });
const directionState = await page.evaluate(() => ({
  applicationDirection: document.documentElement.dir,
  cardDirection: document.getElementById('newsGrid')?.dataset.newsDir,
}));
if (directionState.applicationDirection !== 'ltr' || directionState.cardDirection !== 'rtl') {
  throw new Error(`Reader text-direction preference escaped the article cards: ${JSON.stringify(directionState)}`);
}
const articleOpener = page.locator(`.news-card[data-news-id="${baselineId}"] [data-action="open"]`);
await articleOpener.click();
const articleDialog = page.locator('#newsDialog');
await articleDialog.waitFor({ state: 'visible' });
if (await articleDialog.getAttribute('aria-modal') !== 'true'
  || !(await articleDialog.getAttribute('aria-labelledby'))) {
  throw new Error('The reader article dialog is missing its accessible modal semantics.');
}
const dialogFocusables = articleDialog.locator('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])');
const firstDialogControl = dialogFocusables.first();
const lastDialogControl = dialogFocusables.last();
await lastDialogControl.focus();
await page.keyboard.press('Tab');
if (!(await firstDialogControl.evaluate(element => element === document.activeElement))) {
  throw new Error('Reader dialog focus did not wrap from the last control to the first.');
}
await page.keyboard.press('Shift+Tab');
if (!(await lastDialogControl.evaluate(element => element === document.activeElement))) {
  throw new Error('Reader dialog focus did not wrap backward from the first control.');
}
await page.keyboard.press('Escape');
await articleDialog.waitFor({ state: 'hidden' });
if (!(await articleOpener.evaluate(element => element === document.activeElement))) {
  throw new Error('Closing the reader dialog did not restore focus to its opener.');
}
publications = [...publications, {
  id: newId,
  message_text: 'E2E newly published item',
  source_name: 'Browser test source',
  published_at: new Date().toISOString(),
  created_at: new Date().toISOString(),
  relevance_score: 0.9,
}];
await page.locator('#refreshButton').click();
await page.locator(`.news-card[data-news-id="${newId}"]`).waitFor({ state: 'visible' });
await page.waitForFunction(() => window.__beeE2ENotifications?.some(item => item.body.includes('E2E newly published item')));

// Turn the test preference back off so a future local run starts from a clean
// account state, and ensure the browser did not raise uncaught JavaScript errors.
await page.goto(new URL('/user/settings', baseUrl).toString(), { waitUntil: 'domcontentloaded' });
await page.locator('#app:not(.hidden)').waitFor({ state: 'visible' });
if (await notificationToggle.isChecked()) await notificationLabel.click();
if (await notificationToggle.isChecked()) throw new Error('The browser-notification switch did not toggle off through its visible track.');
await page.locator('#directionSelect').selectOption('auto');
await page.locator('#saveSettingsButton').click();
await page.getByText('Saved just now.', { exact: true }).waitFor({ state: 'visible' });
if (errors.length) throw new Error(`Uncaught User-service browser errors: ${errors.join(' | ')}`);

console.log(JSON.stringify({ user: username, notifications: 'persisted and delivered', textDirection: 'limited to article cards', uncaughtErrors: errors.length }));
} finally {
  await browser.close().catch(() => {});
}
