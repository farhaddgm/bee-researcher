import { chromium } from 'playwright';

const baseUrl = process.env.BEE_ADMIN_URL || 'http://127.0.0.1:8010/admin';
const username = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME;
const password = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if (!username || !password) throw new Error('Admin bootstrap credentials are not available.');

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  locale: 'en-US',
  serviceWorkers: 'block',
});
const page = await context.newPage();
page.setDefaultTimeout(12000);
let incidentSeverity = 'critical';
let incidentFixtureRequests = 0;
await page.route(/\/admin\/api\/incidents(?:\?.*)?$/, route => {
  incidentFixtureRequests += 1;
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      incidents: [{
        id: 'locale-freshness-fixture',
        assistant_id: '00000000-0000-4000-8000-000000000001',
        assistant_name: 'Locale test assistant',
        severity: incidentSeverity,
        status: 'open',
        is_freshness_alert: true,
        last_success_at: null,
        source_count: 3,
      }],
    }),
  });
});
await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
await page.locator('#loginUser').fill(username);
await page.locator('#loginPass').fill(password);
await page.locator('#loginForm button[type="submit"], #loginSubmit').click();
await page.locator('#app:not(.hidden)').waitFor({ state: 'visible' });

const languages = await page.locator('[data-language-select] option').evaluateAll(options =>
  [...new Set(options.map(option => option.value).filter(Boolean))],
);
if (!languages.includes('en') || !languages.includes('fa')) {
  throw new Error(`Expected English and Persian locale options, got: ${languages.join(', ')}`);
}

const persianSpecific = /[پچژگک‌ی]/;
const supportTitles = {
  fa: 'پشتیبانی', en: 'Support', tr: 'Destek', ar: 'الدعم',
  it: 'Supporto', es: 'Soporte', de: 'Support', fr: 'Assistance',
};
const collectionAlerts = {
  fa: { title: 'تأخیر در خزش و تحلیل', detail: 'برای این دستیار منبع فعال وجود دارد، اما اجرای موفق اخیر ثبت نشده یا بیش از ۳۶ ساعت از آن گذشته است.', last: 'آخرین اجرای موفق', none: 'اجرای موفقی ثبت نشده', severity: { critical: 'بحرانی', warning: 'هشدار' }, sources: 'منابع فعال', action: 'بررسی زمان‌بندی' },
  en: { title: 'Collection and analysis are delayed', detail: 'This assistant has enabled sources, but no successful run is recorded or the last run was more than 36 hours ago.', last: 'Last successful run', none: 'No successful run recorded', severity: { critical: 'Critical', warning: 'Warning' }, sources: 'Enabled sources', action: 'Review schedule' },
  tr: { title: 'Toplama ve analiz gecikiyor', detail: 'Bu asistanda etkin kaynaklar var ancak başarılı bir çalışma yok veya son çalışmanın üzerinden 36 saatten fazla geçti.', last: 'Son başarılı çalışma', none: 'Başarılı çalışma kaydı yok', severity: { critical: 'Kritik', warning: 'Uyarı' }, sources: 'Etkin kaynaklar', action: 'Zamanlamayı incele' },
  ar: { title: 'تأخر الجمع والتحليل', detail: 'توجد مصادر مفعّلة لهذا المساعد، لكن لا يوجد تشغيل ناجح أو مضى على آخر تشغيل أكثر من ٣٦ ساعة.', last: 'آخر تشغيل ناجح', none: 'لا يوجد تشغيل ناجح مسجل', severity: { critical: 'حرج', warning: 'تحذير' }, sources: 'المصادر المفعّلة', action: 'مراجعة الجدول' },
  it: { title: 'Raccolta e analisi in ritardo', detail: 'Questo assistente ha fonti attive, ma non risulta un’esecuzione riuscita o l’ultima risale a oltre 36 ore fa.', last: 'Ultima esecuzione riuscita', none: 'Nessuna esecuzione riuscita registrata', severity: { critical: 'Critico', warning: 'Avviso' }, sources: 'Fonti attive', action: 'Rivedi la pianificazione' },
  es: { title: 'Recopilación y análisis retrasados', detail: 'Este asistente tiene fuentes activas, pero no hay ejecuciones correctas o la última fue hace más de 36 horas.', last: 'Última ejecución correcta', none: 'No hay ejecuciones correctas registradas', severity: { critical: 'Crítico', warning: 'Aviso' }, sources: 'Fuentes activas', action: 'Revisar programación' },
  de: { title: 'Sammlung und Analyse sind verzögert', detail: 'Für diesen Assistenten sind Quellen aktiviert, aber es gibt keinen erfolgreichen Lauf oder der letzte liegt mehr als 36 Stunden zurück.', last: 'Letzter erfolgreicher Lauf', none: 'Kein erfolgreicher Lauf erfasst', severity: { critical: 'Kritisch', warning: 'Warnung' }, sources: 'Aktive Quellen', action: 'Zeitplan prüfen' },
  fr: { title: 'Collecte et analyse en retard', detail: 'Cet assistant possède des sources actives, mais aucune exécution réussie n’est enregistrée ou la dernière date de plus de 36 heures.', last: 'Dernière exécution réussie', none: 'Aucune exécution réussie enregistrée', severity: { critical: 'Critique', warning: 'Avertissement' }, sources: 'Sources actives', action: 'Vérifier le calendrier' },
};
const viewNames = await page.locator('.nav-btn[data-view]').evaluateAll(nodes => [...new Set(nodes.map(node => node.dataset.view).filter(Boolean))]);
for (const language of languages) {
  await page.evaluate(value => window.setLanguage?.(value), language);
  await page.evaluate(() => window.setView?.('support'));
  await page.waitForFunction(() => document.querySelector('#view-support')?.classList.contains('active'));
  await page.waitForFunction(() => Boolean(document.querySelector('#view-support [data-support-v4-my-list]')));
  await page.waitForTimeout(350);
  const snapshot = await page.evaluate(() => ({
    lang: document.documentElement.lang,
    dir: document.documentElement.dir,
    labels: [...document.querySelectorAll('[data-label-fa][data-label-en]')]
      .map(node => ({
        fa: node.dataset.labelFa,
        text: node.querySelector('.nav-text')?.textContent?.trim() || node.textContent.trim(),
      }))
      .filter(item => item.text),
    supportTitle: document.querySelector('#view-support h2')?.textContent?.trim() || '',
    supportFields: [...document.querySelectorAll('#view-support [data-support-v4-form] label')]
      .map(node => node.textContent.trim()).filter(Boolean),
    supportCategories: [...document.querySelectorAll('#supportV4Category option')]
      .map(node => node.textContent.trim()).filter(Boolean),
  }));
  const expectedDir = language === 'fa' || language === 'ar' ? 'rtl' : 'ltr';
  if (snapshot.lang !== language || snapshot.dir !== expectedDir) {
    throw new Error(`Locale metadata mismatch for ${language}: ${snapshot.lang}/${snapshot.dir}`);
  }
  if (!snapshot.labels.length || (language === 'fa'
    ? snapshot.labels.some(item => item.text !== item.fa)
    : snapshot.labels.some(item => persianSpecific.test(item.text)))) {
    throw new Error(`Mixed or empty navigation copy detected for locale ${language}`);
  }
  if (snapshot.supportTitle !== supportTitles[language]
    || snapshot.supportFields.length < 3 || snapshot.supportCategories.length < 9
    || (language !== 'fa' && [...snapshot.supportFields, ...snapshot.supportCategories].some(text => persianSpecific.test(text)))) {
    throw new Error(`Support form copy is incomplete or mixed for locale ${language}: ${JSON.stringify(snapshot)}`);
  }
  for (const view of viewNames) {
    await page.evaluate(({ locale, targetView }) => {
      window.setLanguage?.(locale);
      window.setView?.(targetView);
    }, { locale: language, targetView: view });
    await page.waitForFunction(targetView => document.querySelector(`#view-${CSS.escape(targetView)}`)?.classList.contains('active'), view);
    const header = await page.evaluate(() => ({
      lang: document.documentElement.lang,
      dir: document.documentElement.dir,
      title: document.getElementById('pageTitle')?.textContent?.trim() || '',
      selectedView: document.querySelector('.nav-btn.active')?.dataset.view || '',
    }));
    if (header.lang !== language || header.dir !== expectedDir || header.selectedView !== view
      || !header.title || (language !== 'fa' && persianSpecific.test(header.title))) {
      throw new Error(`Page header did not stay translated for ${language}/${view}: ${JSON.stringify(header)}`);
    }
  }
  console.log(`locale verified: ${language} (${viewNames.length} page headings)`);
}

// Exercise the separately authored operational alert copy as rendered UX,
// not just as static strings. This catches missing locale branches and
// regressions where a severity/field label silently falls back to English.
// Keep Operations inactive while switching language: production navigation
// schedules a background incident refresh when entering that view. The test
// explicitly awaits each fixture request below, so it never races that timer.
await page.evaluate(() => window.setView?.('overview'));
await page.waitForFunction(() => document.querySelector('#view-overview')?.classList.contains('active'));
async function refreshIncidentFixture(severity = 'critical') {
  incidentSeverity = severity;
  const before = incidentFixtureRequests;
  const runtime = await page.evaluate(async () => {
    const available = typeof window.loadIncidents === 'function';
    if (available) await window.loadIncidents(true);
    return {
      available,
      view: document.querySelector('.nav-btn.active')?.dataset.view || '',
      toast: document.getElementById('toast')?.textContent?.trim() || '',
      loadedFor: typeof state !== 'undefined' ? state.incidentsLoadedFor : 'unavailable',
      authenticated: typeof state !== 'undefined' && Boolean(state.currentUser),
      loadSource: available ? window.loadIncidents.toString() : '',
    };
  });
  if (!runtime.available || incidentFixtureRequests <= before) {
    throw new Error(`Incident locale fixture did not receive a fresh API request (runtime=${JSON.stringify(runtime)}, before=${before}, after=${incidentFixtureRequests}).`);
  }
}
await refreshIncidentFixture();
await page.waitForTimeout(30);
for (const language of languages) {
  const expected = collectionAlerts[language];
  for (const severity of ['critical', 'warning']) {
    await page.evaluate(value => window.setLanguage?.(value), language);
    await refreshIncidentFixture(severity);
    // The bootstrap account used by CI may not be an owner. In that case the
    // Operations view is intentionally hidden, but its translated renderer is
    // still safe to inspect without pretending the user has owner access.
    await page.locator('#incidentRows .incident-item').waitFor({ state: 'attached' });
    const expectedSeverity = expected?.severity?.[severity];
    try {
      await page.waitForFunction(value =>
        document.querySelector('#incidentRows .incident-item .incident-severity')?.textContent?.trim() === value,
        expectedSeverity,
      );
    } catch (error) {
      const actualSeverity = await page.locator('#incidentRows .incident-item .incident-severity').textContent().catch(() => 'missing');
      throw new Error(`Collection alert severity did not refresh for ${language}/${severity}: expected ${expectedSeverity}, got ${actualSeverity?.trim() || 'empty'}; ${error.message}`);
    }
    const rendered = (await page.locator('#incidentRows .incident-item').innerText()).replace(/\s+/g, ' ').trim();
    const requiredCopy = [expected?.title, expected?.detail, expected?.last, expected?.none,
      expected?.severity[severity], expected?.sources, expected?.action];
    if (!expected || requiredCopy.some(text => !text || !rendered.includes(text))) {
      throw new Error(`Collection freshness alert is untranslated for ${language}/${severity}: ${rendered}`);
    }
  }
  console.log(`operational alerts verified: ${language}`);
}

// A report word that also exists in the UX dictionary must not be partially
// translated as the admin switches language. Use an isolated client fixture;
// no article or publication is created or edited on the server.
for (const language of languages) {
  await page.evaluate(locale => {
    window.setLanguage(locale);
    window.setView('content');
    state.publications = [{ id: 'report-language-fixture', status: 'preview', message_text: 'خبر', source_name: 'TechCrunch', created_at: new Date().toISOString() }];
    renderPublications();
    openPublication('report-language-fixture');
    translateStaticCopy();
  }, language);
  for (const selector of ['.publication-news-cell button', '#articleDetail .article-title', '#articleDetail .article-body']) {
    const text = (await page.locator(selector).first().textContent()).trim();
    if (text !== 'خبر') throw new Error(`Report prose was changed by UX locale ${language}: ${selector} = ${text}`);
  }
  await page.evaluate(() => document.querySelector('#closeDrawer')?.click());
}
console.log('Report/UX language isolation passed: original report prose preserved in 8 backoffice locales.');
await browser.close();
console.log(JSON.stringify({ checkedLocales: languages.length, checkedOperationalAlerts: languages.length * 2, languages }));
