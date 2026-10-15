import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';

// CDP awaitPromise does not retain a JavaScript promise strongly. Chromium
// may collect a pending refresh and Playwright 1.55 rewrites the protocol's
// "Promise was collected" as a misleading navigation error. Retain the run
// in the document and poll its actual terminal state, not an arbitrary delay.
// A rejected refresh, real navigation or timeout must still fail the test.
export async function refreshAdmin(page, {collectGarbage = false} = {}) {
  const key = randomUUID();
  await page.evaluate(key => {
    const runs = window.__beeE2ERefreshRuns ||= Object.create(null);
    const run = runs[key] = {status:'running', error:null, promise:null};
    run.promise = Promise.resolve().then(() => window.loadAll()).then(
      () => {run.status = 'completed';},
      error => {run.error = String(error?.message || error);run.status = 'failed';},
    );
  }, key);
  try {
    if (collectGarbage) {
      const cdp = await page.context().newCDPSession(page);
      try {await cdp.send('HeapProfiler.collectGarbage');}
      finally {await cdp.detach();}
    }
    await page.waitForFunction(key => {
      const run = window.__beeE2ERefreshRuns?.[key];
      return run?.status === 'completed' || run?.status === 'failed';
    }, key);
    const result = await page.evaluate(key => {
      const run = window.__beeE2ERefreshRuns[key];
      return {status:run.status, error:run.error};
    }, key);
    assert.equal(result.status, 'completed', result.error || 'Admin refresh failed');
  } finally {
    // Do not swallow page closure/navigation: losing the original document
    // is a real failure, not a reason to replay a request or accept the test.
    await page.evaluate(key => {delete window.__beeE2ERefreshRuns?.[key];}, key);
  }
}
