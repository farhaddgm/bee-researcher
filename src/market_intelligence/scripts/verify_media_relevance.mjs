import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.BEE_ADMIN_URL || 'http://127.0.0.1:8010/admin';
const username = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME;
const password = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if (!username || !password) throw new Error('Media E2E requires isolated credentials.');
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
page.setDefaultTimeout(12000);
const errors = [];
page.on('pageerror', error => errors.push(error.message));
let health = 'healthy';
let searchPage = -1;
let rows = [];
let quotaFailure = false;
const json = (route, value) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(value) });
await page.route(/\/health(?:\?.*)?$/, route => json(route, { status: health, dependencies: { postgres: 'healthy', redis: 'healthy' } }));
await page.route(/\/admin\/api\/assistants\/[^/]+\/source-suggestions(?:\?.*)?$/, route => {
  if (route.request().method() === 'POST') {
    if (quotaFailure) return json(route, { count: 0, provider_status: 'provider_quota_exhausted' });
    const input = route.request().postDataJSON();
    assert.equal(input.name, '人工知能');
    searchPage = input.page || 0;
    rows = Array.from({ length: 10 }, (_, n) => ({ id: `candidate-${searchPage}-${n}`, name: `Media ${searchPage}-${n}`, draft: { name: `Media ${searchPage}-${n}`, homepage_url: `https://media-${searchPage}-${n}.example.org`, evidence: [`https://media-${searchPage}-${n}.example.org/news`], summary: 'Public technology news', language: 'en', region: 'global' } }));
    return json(route, { count: 10, provider: 'openai_web_search', provider_status: 'succeeded' });
  }
  return json(route, { suggestions: rows, can_approve: true });
});
await page.route(/\/sources\/draft$/, route => json(route, { draft: { name: 'Unknown fixture', provider_status: 'provider_quota_exhausted' }, verification: { status: 'provider_unavailable', provider_status: 'provider_quota_exhausted', message: 'Old misleading fallback' } }));
await page.route(/\/source-suggestions\/candidate-[^/]+\/(approve|reject)$/, route => {
  const id = new URL(route.request().url()).pathname.split('/').at(-2);
  rows = rows.filter(row => row.id !== id);
  return json(route, { status: 'completed' });
});
try {
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.locator('#loginUser').fill(username);
  await page.locator('#loginPass').fill(password);
  await page.locator('#loginForm button[type="submit"], #loginSubmit').click();
  await page.locator('#app:not(.hidden)').waitFor({ state: 'visible' });
  await page.waitForFunction(() => typeof state !== 'undefined' && state.health?.status === 'healthy');
  const checking = /Checking|در حال بررسی|Kontrol|التحقق/;
  for (const locale of ['fa', 'en', 'tr', 'ar', 'es', 'it', 'de', 'fr']) {
    await page.evaluate(locale => { window.setLanguage(locale); window.setView('overview'); }, locale);
    await page.waitForTimeout(150);
    assert(!checking.test(await page.locator('#kpiHealth').innerText()), `Health stayed Checking in ${locale}`);
    assert.equal(await page.locator('#kpiHealthDot').getAttribute('class'), 'up');
    await page.evaluate(() => window.setView('settings'));
    // A language/view change can retain the old cursor coordinates. Exercise
    // a fresh real hover, rather than assuming it emits pointerover again.
    await page.mouse.move(0, 0);
    await page.locator('#projectRelevanceInfo').hover();
    await page.waitForFunction(() => document.getElementById('beeUiTooltip')?.hidden === false);
    const help = await page.locator('#beeUiTooltip').innerText();
    assert(help.length > 30, `Missing threshold explanation in ${locale}`);
    if (!['fa', 'ar'].includes(locale)) assert(!/[پچژگک]/.test(help), `Persian leaked into ${locale}`);
    await page.locator('#projectRelevanceInfo').focus();
    assert.equal(await page.locator('#beeUiTooltip').evaluate(node => node.hidden), false);
  }
  await page.evaluate(() => { window.setLanguage('en'); window.setView('sources'); });
  await page.locator('#sourceSuggestionBtn').click();
  await page.locator('#mediaSuggestKeyword').fill('人工知能');
  await page.locator('#modalSubmit').click();
  await page.waitForFunction(() => document.querySelectorAll('#sourceSuggestionsRows .channel-card').length === 10);
  assert.equal(searchPage, 0);
  assert.match(await page.locator('#mediaDiscoveryProvider').innerText(), /OpenAI/);
  assert.equal(await page.locator('#sourceSuggestionsRows a').count(), 10);
  await page.locator('#refreshMediaDiscovery').click();
  await page.waitForFunction(() => document.querySelector('#sourceSuggestionsRows')?.textContent.includes('Media 1-0'));
  assert.equal(searchPage, 1);
  assert.equal(await page.locator('#sourceSuggestionsRows .channel-card').count(), 10);
  await page.locator('[data-media-reject]').first().click();
  await page.waitForFunction(() => document.querySelectorAll('#sourceSuggestionsRows .channel-card').length === 9);
  assert(!rows.some(row => row.id === 'candidate-1-0'));

  await page.evaluate(() => {
    closeModal(); window.setView('publications');
    state.publications = ['selected','borderline','rejected','pending'].map((s,n)=>({id:'decision-'+n,status:'preview',message_text:'Original report for '+s,source_name:'Fixture',relevance_state:s,review_only:s!=='selected',publishable:s==='selected',can_approve:s==='borderline',analysis_ready:true,relevance_score:s==='pending'?null:.7,relevance_threshold:.75,relevance_topic:'AI',relevance_reason:'Original classification evidence',relevance_evidence:['Exact original quote']}));
    document.getElementById('publicationStatus').value='';renderPublications();
  });
  assert.equal(await page.locator('#publicationRows tr').count(),4);
  assert.match(await page.locator('#publicationRows').innerText(),/Ready to publish/);
  for(const locale of ['fa','en','tr','ar','es','it','de','fr']){
    await page.evaluate(locale=>{window.setLanguage(locale);renderPublications();openPublication('decision-3')},locale);
    assert.equal(await page.locator('#articleDetail button').count(),0,'Pending AI exposed a publish action');
    assert((await page.locator('#articleDetail').innerText()).includes('Exact original quote'),'UX localization mutated AI source evidence');
    await page.locator('#closeDrawer').click();
  }
  await page.evaluate(()=>{window.setLanguage('en');openPublication('decision-1')});
  assert.equal(await page.locator('#articleDetail button').count(),1);
  assert.match(await page.locator('#articleDetail').innerText(),/Topic threshold: 0.75/);
  await page.locator('#closeDrawer').click();

  quotaFailure = true;
  for (const locale of ['fa', 'en', 'tr', 'ar', 'es', 'it', 'de', 'fr']) {
    await page.evaluate(locale => { closeModal(); window.setLanguage(locale); window.setView('sources'); }, locale);
    await page.locator('#addSourceBtn').click();
    await page.locator('#mediaDraftName').fill('Unknown fixture');
    await page.locator('#modalSubmit').click();
    await page.locator('#mediaManualReview').waitFor();
    const result = await page.locator('.media-discovery-result').innerText();
    assert(result.includes('Codex'), `Missing actionable API billing explanation in ${locale}`);
    assert(!result.includes('Old misleading fallback'), 'Raw provider fallback overrode localized explanation');
    await page.evaluate(() => closeModal());
    await page.locator('#sourceSuggestionBtn').click();
    await page.locator('#mediaSuggestKeyword').fill('Unknown fixture');
    await page.locator('#modalSubmit').click();
    await page.waitForFunction(() => document.querySelector('.media-discovery-result')?.textContent.includes('Codex'));
  }
  await page.evaluate(() => closeModal());

  // A terminal failure must replace the prior success, not keep a loading
  // string or hardcoded healthy state when a locale renderer reruns.
  await page.evaluate(() => { state.health = { status: 'unavailable' }; window.setLanguage('en'); window.setView('overview'); });
  await page.waitForTimeout(200);
  assert.equal(await page.locator('#kpiHealthDot').getAttribute('class'), 'down');
  assert(!checking.test(await page.locator('#kpiHealth').innerText()));
  assert.equal(errors.length, 0, `Uncaught browser errors: ${errors.join('; ')}`);
  console.log('Media/Overview E2E passed: 8 locales, tooltips, health, 10 cards, refresh, cleanup, score decisions, original evidence and actionable API billing failures.');
} finally {
  await browser.close();
}
