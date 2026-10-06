import { chromium } from 'playwright';

// Regression probe for an important class of UI defects: an element can look
// clickable while a responsive layer above it receives the pointer event.
// This intentionally uses page.mouse.click rather than locator.click so it
// exercises the browser hit-test at the button's visible centre.
const baseUrl = process.env.BEE_ADMIN_URL || 'https://researcher.beeproject.ir/admin';
const username = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME;
const password = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if (!username || !password) throw new Error('Admin bootstrap credentials are unavailable.');

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1920, height: 980 } });
await context.addInitScript(() => {
  localStorage.setItem('research_bee_admin_language', 'en');
  localStorage.removeItem('research_bee_sidebar_collapsed');
});
const page = await context.newPage();
page.setDefaultTimeout(15000);
const pageErrors = [];
page.on('pageerror', error => pageErrors.push(String(error)));

async function waitForWorkspace() {
  await page.locator('#app:not(.hidden)').waitFor({ state: 'visible' });
  await page.waitForFunction(() => {
    const select = document.getElementById('workspaceSelect');
    return Boolean(select?.value && select.options.length);
  });
}

async function hitTest(buttonId) {
  return page.evaluate(id => {
    const button = document.getElementById(id);
    if (!button) return { missing: true };
    const rect = button.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const hit = document.elementsFromPoint(x, y).slice(0, 8).map(node => ({
      tag: node.tagName,
      id: node.id || null,
      classes: node.className || null,
      pointerEvents: getComputedStyle(node).pointerEvents,
      zIndex: getComputedStyle(node).zIndex,
    }));
    return {
      rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
      visible: Boolean(rect.width && rect.height),
      disabled: button.disabled,
      topHit: hit[0] || null,
      hit,
    };
  }, buttonId);
}

async function openWithPhysicalClick(view, buttonId, fieldId, viewport) {
  await page.setViewportSize(viewport);
  await page.locator(`.nav-btn[data-view="${view}"]`).click();
  const button = page.locator(`#${buttonId}`);
  await button.waitFor({ state: 'visible' });
  await page.waitForTimeout(120);
  const diagnostic = await hitTest(buttonId);
  if (diagnostic.missing || !diagnostic.visible || diagnostic.disabled) {
    throw new Error(`${viewport.width}px ${buttonId} unavailable: ${JSON.stringify(diagnostic)}`);
  }
  const { left, top, width, height } = diagnostic.rect;
  await page.mouse.click(left + width / 2, top + height / 2);
  try {
    await page.locator(`#modalRoot:not(.hidden) #${fieldId}`).waitFor({ state: 'visible', timeout: 2500 });
  } catch (error) {
    throw new Error(`${viewport.width}px ${buttonId} physical click did not open its modal. hit=${JSON.stringify(diagnostic)} error=${error.message}`);
  }
  await page.locator('#modalRoot .modal-close').click();
  await page.locator('#modalRoot.hidden').waitFor({ state: 'attached' });
  return { viewport: viewport.width, view, buttonId, topHit: diagnostic.topHit };
}

await page.goto(new URL("/admin/login-up",baseUrl).href, { waitUntil: 'domcontentloaded', timeout: 30000 });
await page.locator('#loginUser').fill(username);
await page.locator('#loginPass').fill(password);
await page.locator('#loginSubmit').click();
await waitForWorkspace();

const results = [];
const widths = [1920, 1680, 1440, 1280, 1120, 1000, 900, 800];
for (const width of widths) {
  const viewport = { width, height: 980 };
  results.push(await openWithPhysicalClick('sources', 'addSourceBtn', 'directSourceName', viewport));
  results.push(await openWithPhysicalClick('topics', 'addTopicBtn', 'draftTopicName', viewport));
}

await browser.close();
if (pageErrors.length) throw new Error(`Browser errors: ${pageErrors.join(' | ')}`);
console.log(JSON.stringify({ results, pageErrors }));
