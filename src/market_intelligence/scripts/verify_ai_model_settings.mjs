import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.BEE_ADMIN_URL;
const username = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME;
const password = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if (!base || !username || !password || process.env.MARKET_INTELLIGENCE_ENVIRONMENT !== 'test') {
  throw new Error('Model E2E requires an isolated test application and credentials.');
}
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
page.setDefaultTimeout(15000);
const originals = new Map();
let created = '';
async function api(path, method = 'GET', body) {
  return page.evaluate(async ({ path, method, body }) => {
    const csrf = document.cookie.split('; ').find(x => x.startsWith('research_bee_admin_csrf='))?.split('=').slice(1).join('=');
    const response = await fetch(path, { method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': decodeURIComponent(csrf || '') }, ...(body ? { body: JSON.stringify(body) } : {}) });
    return { status: response.status, data: await response.json() };
  }, { path, method, body });
}
async function chooseAssistant(id) {
  await page.locator('#workspaceSelect').selectOption(id);
  await page.waitForFunction(id => state.assistantId === id && state.runtimeSettings?.assistant_id === id, id);
  await page.locator('.nav-btn[data-view="settings"]').click();
  await page.locator('#analysisModel:not([disabled])').waitFor();
}
async function saveModel(model) {
  await page.locator('#analysisModel').selectOption(model);
  const response = page.waitForResponse(r => r.url().endsWith('/runtime-settings') && r.request().method() === 'PUT');
  await page.locator('#saveAnalysisModelBtn').click();
  const saved = await response;
  assert.equal(saved.status(), 200);
  assert.equal((await saved.json()).analysis_model, model);
  await page.waitForFunction(model => state.runtimeSettings?.analysis_model === model && document.getElementById('saveAnalysisModelBtn').disabled, model);
}
try {
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.locator('#loginUser').fill(username);
  await page.locator('#loginPass').fill(password);
  await page.locator('#loginSubmit').click();
  await page.locator('#app:not(.hidden)').waitFor();
  await page.waitForFunction(() => state.runtimeSettings?.assistant_id === state.assistantId);
  const assistants = (await api('/admin/api/assistants')).data.assistants.filter(x => !x.deleted_at);
  assert(assistants.length, 'The isolated application must have its bootstrap workspace.');
  {
    const response = await api('/admin/api/assistants', 'POST', { name: 'Model isolation E2E', slug: 'model-e2e-' + Date.now(), business_name: '', description: 'Synthetic isolated model selection fixture', config: { runtime: { analysis_model: 'gpt-5.6-luna', schedule_slots: [{ weekday: 1, time: '14:00' }] } } });
    assert.equal(response.status, 200);
    created = response.data.id;
    assistants.unshift(response.data);
    await page.evaluate(() => loadAll());
  }
  for (const { id } of assistants.slice(0, 2)) originals.set(id, (await api(`/admin/api/assistants/${id}/runtime-settings`)).data.analysis_model);
  const first = assistants[0].id, second = assistants[1].id;
  await chooseAssistant(first);
  const modelIds = await page.locator('#analysisModel option').evaluateAll(nodes => nodes.map(x => x.value));
  for (const id of ['gpt-6.1-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4']) assert(modelIds.includes(id), `Missing ${id}`);
  for (const locale of ['fa', 'en', 'tr', 'ar', 'es', 'it', 'de', 'fr']) {
    await page.evaluate(locale => window.setLanguage(locale), locale);
    await page.locator('#analysisModelInfo').hover();
    await page.waitForFunction(() => getComputedStyle(document.getElementById('analysisModelHelp')).opacity === '1');
    const text = await page.locator('#analysisModelHelp').innerText();
    assert(text.length > 100, `Incomplete tooltip in ${locale}`);
    if (!['fa', 'ar'].includes(locale)) assert(!/[پچژگک]/.test(text), `Persian copy in ${locale}`);
    assert.equal(await page.locator('#analysisModel').count(), 1);
    assert.equal(await page.locator('#view-schedule #analysisModel').count(), 0);
    assert.equal(await page.locator('#assistantAISettingsCard').evaluate(node => node.previousElementSibling?.classList.contains('page-head')), true);
    assert.equal(await page.locator('#saveAnalysisModelBtn').isDisabled(), true);
  }
  // Both new choices really persist through the API and a browser reload.
  const initial = await page.locator('#analysisModel').inputValue();
  if (initial === 'gpt-6.1-sol') await saveModel('gpt-6-luna');
  await saveModel('gpt-6.1-sol');
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => state.runtimeSettings?.assistant_id === state.assistantId);
  await chooseAssistant(first);
  assert.equal(await page.locator('#analysisModel').inputValue(), 'gpt-6.1-sol');
  await saveModel('gpt-6-luna');
  // Publication controls must not send a default model and undo the choice.
  await page.locator('.nav-btn[data-view="schedule"]').click();
  const publicationResponse = page.waitForResponse(r => r.url().endsWith('/runtime-settings') && r.request().method() === 'PUT');
  await page.locator('#saveScheduleBtn').click();
  const publication = await publicationResponse;
  assert.equal(publication.status(), 200);
  assert.equal(publication.request().postDataJSON().analysis_model, undefined);
  assert.equal((await publication.json()).analysis_model, 'gpt-6-luna');
  await chooseAssistant(second);
  assert.equal(await page.locator('#analysisModel').inputValue(), originals.get(second));
  await chooseAssistant(first);
  assert.equal(await page.locator('#analysisModel').inputValue(), 'gpt-6-luna');
  // An ordinary project admin/editor can access model settings, but owner
  // capacity and collection controls stay hidden. Viewer gets no write UI.
  await page.evaluate(() => { state.currentUser = { ...state.currentUser, is_owner: false, role: 'assistant_admin' }; applyRoleVisibility(); window.setView('settings'); });
  assert.equal(await page.locator('#analysisModel').isVisible(), true);
  assert.equal(await page.locator('#limitsCard').isVisible(), false);
  assert.equal(await page.locator('#collectionSettingsCard').isVisible(), false);
  await page.evaluate(() => { state.currentUser = { ...state.currentUser, role: 'viewer' }; applyRoleVisibility(); });
  assert.equal(await page.locator('.nav-btn[data-view="settings"]').isVisible(), false);
  assert.equal(errors.length, 0, `Browser errors: ${errors.join('; ')}`);
  console.log('AI model settings E2E passed: 8 locales, new and legacy options, real save/reload, per-assistant isolation, publication preservation, role visibility.');
} finally {
  // Restore only explicit, supported selections; never replace a deployment
  // default/unknown legacy ID with the first dropdown option.
  for (const [id, model] of originals) {
    if (['gpt-6.1-sol', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4'].includes(model)) await api(`/admin/api/assistants/${id}/runtime-settings`, 'PUT', { analysis_model: model });
  }
  if (created) await api(`/admin/api/assistants/${created}`, 'DELETE');
  await browser.close();
}
