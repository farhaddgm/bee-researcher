import { chromium } from 'playwright';

const baseUrl = process.env.BEE_ADMIN_URL || 'http://127.0.0.1:8010/admin';
const username = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME;
const password = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if (!username || !password) throw new Error('Support E2E requires isolated owner credentials.');

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'en-US' });
page.setDefaultTimeout(12_000);
const pageErrors = [];
const failedSupportRequests = [];
page.on('pageerror', error => pageErrors.push(error.message));
page.on('response', response => {
  if (response.url().includes('/admin/api/support/tickets') && response.status() >= 400) {
    failedSupportRequests.push(`${response.status()} ${response.url()}`);
  }
});

try {
  await page.goto(new URL("/admin/login-up",baseUrl).href, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await page.locator('#loginUser').fill(username);
  await page.locator('#loginPass').fill(password);
  await page.locator('#loginForm button[type="submit"], #loginSubmit').click();
  await page.locator('#app:not(.hidden)').waitFor({ state: 'visible' });
  await page.evaluate(() => window.setView?.('support'));
  await page.locator('#view-support [data-support-v4-form]').waitFor({ state: 'visible' });
  await page.locator('[data-support-v4-all-list]').waitFor({ state: 'visible' });

  const nonce = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const subject = `Support conversation E2E ${nonce}`;
  const original = `Automated immutable ticket description ${nonce}`;
  const ownerReply = `Owner response persisted ${nonce}`;

  await page.locator('[data-support-v4-category]').selectOption('other');
  await page.locator('[data-support-v4-other]').fill(subject);
  await page.locator('[data-support-v4-body]').fill(original);
  await page.locator('[data-support-v4-priority="high"]').click();
  await page.locator('[data-support-v4-submit]').click();

  const ticket = page.locator('[data-support-v4-all-list] [data-support-v4-ticket]').filter({ hasText: subject }).first();
  await ticket.waitFor({ state: 'visible' });
  await ticket.click();
  const dialog = page.locator('#support-ticket-v4-dialog');
  await dialog.locator('[role="dialog"]').waitFor({ state: 'visible' });
  await page.waitForFunction(() =>
    document.querySelector('#support-ticket-v4-dialog')?.dataset.keyboardA11yBound === '1',
  );
  const dialogControls = dialog.locator('[role="dialog"] button:not([disabled]), [role="dialog"] a[href], [role="dialog"] input:not([disabled]), [role="dialog"] select:not([disabled]), [role="dialog"] textarea:not([disabled]), [role="dialog"] [tabindex]:not([tabindex="-1"])');
  const firstDialogControl = dialogControls.first();
  const lastDialogControl = dialogControls.last();
  if (await dialogControls.count() < 3) throw new Error('The ticket dialog is missing expected keyboard controls.');
  await lastDialogControl.focus();
  await page.keyboard.press('Tab');
  if (!(await firstDialogControl.evaluate(element => element === document.activeElement))) {
    throw new Error('Tab did not wrap from the last control to the first control in the ticket dialog.');
  }
  await page.keyboard.press('Shift+Tab');
  if (!(await lastDialogControl.evaluate(element => element === document.activeElement))) {
    throw new Error('Shift+Tab did not wrap from the first control to the last control in the ticket dialog.');
  }
  if ((await dialog.locator('[data-support-v4-original]').textContent())?.trim() !== original) {
    throw new Error('The original ticket description did not render as immutable conversation content.');
  }
  await dialog.locator('[data-support-v4-dialog-input]').fill(ownerReply);
  await dialog.locator('[data-support-v4-dialog-send]').click();
  await dialog.waitFor({ state: 'hidden' });
  const repliedTicketId = await ticket.getAttribute('data-support-v4-ticket');
  try {
    await page.waitForFunction(ticketId => {
      const active = document.activeElement;
      return active instanceof HTMLElement && active.dataset.supportV4Ticket === ticketId;
    }, repliedTicketId);
  } catch (error) {
    const focusState = await page.evaluate(ticketId => ({
      activeTag: document.activeElement?.tagName || '',
      activeId: document.activeElement?.id || '',
      activeTicketId: document.activeElement?.dataset?.supportV4Ticket || '',
      dialogHidden: document.querySelector('#support-ticket-v4-dialog')?.hidden,
      supportBusy: document.querySelector('#view-support')?.getAttribute('aria-busy'),
      matchingCards: [...document.querySelectorAll('[data-support-v4-ticket]')]
        .filter(node => node.dataset.supportV4Ticket === ticketId)
        .length,
      ticketCards: document.querySelectorAll('[data-support-v4-ticket]').length,
    }), repliedTicketId);
    throw new Error(`Ticket focus was not restored after the thread refreshed (${JSON.stringify(focusState)}): ${error.message}`);
  }

  await page.locator('[data-support-v4-all-list] [data-support-v4-ticket]').filter({ hasText: subject }).first().click();
  await dialog.locator('[data-support-v4-thread] .support-v4-message').filter({ hasText: ownerReply }).waitFor({ state: 'visible' });
  if (!(await dialog.locator('[data-support-v4-thread] .support-v4-message.owner').filter({ hasText: ownerReply }).count())) {
    throw new Error('Owner reply is not identified as an owner-authored conversation message.');
  }
  await dialog.locator('[data-support-v4-dialog-close-ticket]').click();
  await dialog.waitFor({ state: 'hidden' });

  await page.locator('[data-support-v4-all-list] [data-support-v4-ticket]').filter({ hasText: subject }).first().click();
  await dialog.locator('.support-v4-closed-note').waitFor({ state: 'visible' });
  if (await dialog.locator('[data-support-v4-dialog-input], [data-support-v4-dialog-send], [data-support-v4-dialog-close-ticket]').count()) {
    throw new Error('A closed ticket still exposes controls to modify the conversation.');
  }
  await dialog.locator('[data-support-v4-dialog-close]').click();
  await dialog.waitFor({ state: 'hidden' });
  await page.evaluate(() => window.setView?.('assistants'));
  const assistantCreateTrigger = page.locator('#newAssistantBtn');
  await assistantCreateTrigger.waitFor({ state: 'visible' });
  await assistantCreateTrigger.click();
  const genericDialog = page.locator('#modalRoot:not(.hidden) [role="dialog"]');
  await genericDialog.waitFor({ state: 'visible' });
  if ((await genericDialog.getAttribute('aria-modal')) !== 'true'
    || !(await genericDialog.getAttribute('aria-labelledby'))) {
    throw new Error('A standard Admin modal is missing its accessible dialog semantics.');
  }
  const genericControls = genericDialog.locator('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])');
  const genericFirst = genericControls.first();
  const genericLast = genericControls.last();
  await genericLast.focus();
  await page.keyboard.press('Tab');
  if (!(await genericFirst.evaluate(element => element === document.activeElement))) {
    throw new Error('Admin modal focus did not wrap from the last control to the first.');
  }
  await page.keyboard.press('Shift+Tab');
  if (!(await genericLast.evaluate(element => element === document.activeElement))) {
    throw new Error('Admin modal focus did not wrap backward from the first control.');
  }
  await page.keyboard.press('Escape');
  await page.locator('#modalRoot').waitFor({ state: 'hidden' });
  await page.waitForFunction(() => document.activeElement?.id === 'newAssistantBtn');
  if (pageErrors.length || failedSupportRequests.length) {
    throw new Error(`Support E2E errors: page=${pageErrors.join(' | ')} API=${failedSupportRequests.join(' | ')}`);
  }

  // Role boundary: a project user without an explicit portal grant must be
  // rejected by the server, then an owner grant must allow only assigned
  // workspaces. This catches UI-only access control regressions.
  const csrf = await page.evaluate(() => document.cookie.split(';').map(value => value.trim())
    .find(value => value.startsWith('research_bee_admin_csrf='))?.split('=').slice(1).join('=') || '');
  if (!csrf) throw new Error('The admin CSRF cookie was unavailable to the isolated browser test.');
  const fixtureAssistants = [];
  for (const [suffix, name] of [['assigned', 'Portal access fixture'], ['unassigned', 'Portal isolation fixture']]) {
    const fixture = await page.evaluate(async ({ csrfToken, assistantSlug, assistantName }) => {
      const created = await fetch('/admin/api/assistants', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
        body: JSON.stringify({ slug: assistantSlug, name: assistantName, business_name: '', description: 'Temporary isolated browser-test workspace.' }),
      });
      const body = await created.json();
      if (!created.ok) return { status: created.status, body };
      const activated = await fetch(`/admin/api/assistants/${body.id}`, {
        method: 'PATCH', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
        body: JSON.stringify({ status: 'active' }),
      });
      return { status: activated.status, body: { ...body, activated: await activated.json() } };
    }, { csrfToken: csrf, assistantSlug: `e2e-${suffix}-${nonce.replace(/[^a-z0-9]/gi, '').slice(-16)}`, assistantName: `${name} ${nonce}` });
    if (fixture.body?.id) fixtureAssistants.push(fixture.body.id);
    if (fixture.status !== 200) {
      if (fixtureAssistants.length) await page.evaluate(async ({ csrfToken, ids }) => {
        await Promise.all(ids.map(id => fetch(`/admin/api/assistants/${id}`, {
          method: 'DELETE', credentials: 'same-origin',
          headers: { 'X-CSRF-Token': csrfToken },
        })));
      }, { csrfToken: csrf, ids: fixtureAssistants });
      throw new Error(`Could not prepare a real workspace-scoped portal fixture: HTTP ${fixture.status}`);
    }
  }
  const assignedWorkspaceId = fixtureAssistants[0];
  const unassignedWorkspaceId = fixtureAssistants[1];
  const userName = `portal-e2e-${nonce.replace(/[^a-z0-9]/gi, '').slice(-16)}`;
  const userPassword = `Portal-E2E-${nonce}-Aa1!`;
  const createdUser = await page.evaluate(async ({ csrfToken, account, secret, assigned }) => {
    const response = await fetch('/admin/api/users', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ username: account, password: secret, role: 'viewer', assistant_ids: [assigned] }),
    });
    return { status: response.status, body: await response.json() };
  }, { csrfToken: csrf, account: userName, secret: userPassword, assigned: assignedWorkspaceId });
  if (createdUser.status !== 200) throw new Error(`Could not create isolated role-test user: HTTP ${createdUser.status}`);
  const userId = createdUser.body.id;
  const readerPage = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  try {
    const userUrl = new URL('/user', baseUrl).toString();
    await readerPage.goto(userUrl, { waitUntil: 'domcontentloaded' });
    const denied = await readerPage.evaluate(async ({ account, secret }) => {
      const response = await fetch('/user/api/login', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: account, password: secret }),
      });
      return { status: response.status, body: await response.json() };
    }, { account: userName, secret: userPassword });
    if (denied.status !== 403 || denied.body.detail !== 'user portal access denied') {
      throw new Error(`User without a portal grant was not denied: ${JSON.stringify(denied)}`);
    }
    const grant = await page.evaluate(async ({ csrfToken, id }) => {
      const response = await fetch(`/admin/api/users/${id}/user-portal-access`, {
        method: 'PUT', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
        body: JSON.stringify({ enabled: true, feedback_enabled: false }),
      });
      return { status: response.status, body: await response.json() };
    }, { csrfToken: csrf, id: userId });
    if (grant.status !== 200) throw new Error(`Owner portal grant failed: HTTP ${grant.status}`);
    const allowed = await readerPage.evaluate(async ({ account, secret }) => {
      const response = await fetch('/user/api/login', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: account, password: secret }),
      });
      return { status: response.status, body: await response.json() };
    }, { account: userName, secret: userPassword });
    if (allowed.status !== 200 || allowed.body.user_portal_access !== true || allowed.body.user_feedback_access !== false) {
      throw new Error(`Explicitly granted user portal login failed: ${JSON.stringify(allowed)}`);
    }
    const assistants = await readerPage.evaluate(async () => {
      const response = await fetch('/user/api/assistants', { credentials: 'same-origin' });
      if (!response.ok) throw new Error(`Assistant scope returned ${response.status}`);
      return response.json();
    });
    const visibleIds = (assistants.assistants || []).map(item => item.id);
    if (visibleIds.length !== 1 || visibleIds[0] !== assignedWorkspaceId || visibleIds.includes(unassignedWorkspaceId)) {
      throw new Error(`User portal workspace scope was not enforced. Expected only ${assignedWorkspaceId}; got ${visibleIds.join(',')}`);
    }
  } finally {
    await readerPage.close();
    await page.evaluate(async ({ csrfToken, id }) => {
      await fetch(`/admin/api/users/${id}`, {
        method: 'DELETE', credentials: 'same-origin',
        headers: { 'X-CSRF-Token': csrfToken },
      });
    }, { csrfToken: csrf, id: userId });
    await page.evaluate(async ({ csrfToken, ids }) => {
      await Promise.all(ids.map(id => fetch(`/admin/api/assistants/${id}`, {
        method: 'DELETE', credentials: 'same-origin',
        headers: { 'X-CSRF-Token': csrfToken },
      })));
    }, { csrfToken: csrf, ids: fixtureAssistants });
  }
  console.log(JSON.stringify({ support: 'ticket creation, owner reply, immutable body, close state and keyboard focus verified', userPortal: 'default denial, explicit grant, and workspace scope verified', uncaughtErrors: 0 }));
} finally {
  await browser.close();
}
