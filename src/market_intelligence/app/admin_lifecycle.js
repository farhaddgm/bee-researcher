/* Shared extension lifecycle. Feature controllers register, never wrap globals. */
(() => {
  'use strict';
  if (window.BeeAdminLifecycle) return;
  const hooks = new Map(), installed = new Map(), flights = new Map(), samples = [];
  let scope = () => '', errors = 0;
  const clock = () => performance.now();
  function record(owner, name, started, outcome) {
    // Never retain arguments, actor IDs, exceptions, URLs or customer content.
    samples.push({owner, name, duration_ms: Math.round((clock() - started) * 100) / 100, outcome});
    if (samples.length > 100) samples.shift();
  }
  function run(name, phase, context) {
    const pending = [];
    for (const [owner, entry] of hooks) {
      const handler = entry[phase];
      if (!entry.names.includes(name) || typeof handler !== 'function') continue;
      if (phase !== 'before' && entry.scoped !== false && context.scope !== scope()) continue;
      const started = clock();
      try {
        const value = handler(context);
        if (value && typeof value.then === 'function') {
          pending.push(Promise.resolve(value).then(() => record(owner, name, started, 'ok'), () => {
            errors++; record(owner, name, started, 'error');
          }));
        } else record(owner, name, started, 'ok');
      } catch (_) { errors++; record(owner, name, started, 'error'); }
    }
    return Promise.all(pending);
  }
  function register(owner, names, entry) {
    if (!/^[a-z][a-z0-9-]{0,63}$/.test(owner) || !Array.isArray(names)) throw Error('invalid_lifecycle_owner');
    const registered = {...entry, names: [...new Set(names)]};
    hooks.set(owner, registered);
    return () => { if (hooks.get(owner) === registered) hooks.delete(owner); };
  }
  function install(names, getScope) {
    if (getScope) scope = getScope;
    for (const name of names) {
      const original = window[name];
      if (typeof original !== 'function' || original === installed.get(name)) continue;
      const wrapped = function (...args) {
        const context = {name, args, scope: scope(), succeeded: false};
        const execute = () => {
          run(name, 'before', context);
          let value;
          try { value = original.apply(this, args); }
          catch (error) { run(name, 'settled', context); throw error; }
          if (value && typeof value.then === 'function') return Promise.resolve(value).then(async result => {
            // The bootstrap may authorize a default project on first login.
            // Accept that explicit result only if it is still the current
            // scope; never infer it from an arbitrary late completion.
            if (name === 'loadAll' && result?.__beeLifecycleScope === scope()) context.scope = result.__beeLifecycleScope;
            context.succeeded = true; await run(name, 'after', context); await run(name, 'settled', context); return result;
          }, async error => { await run(name, 'settled', context); throw error; });
          context.succeeded = true; run(name, 'after', context); run(name, 'settled', context); return value;
        };
        if (name !== 'loadAll') return execute();
        // Do not share another user's/project's refresh promise. Cleanup by
        // identity so an older completion cannot clear a newer flight.
        const key = context.scope;
        if (flights.has(key)) return flights.get(key);
        const promise = Promise.resolve().then(execute);
        flights.set(key, promise);
        const clean = () => { if (flights.get(key) === promise) flights.delete(key); };
        promise.then(clean, clean);
        return promise;
      };
      wrapped.__beeLifecycle = true;
      if (name === 'loadAll') wrapped.__adminPerformanceSingleFlight = true;
      installed.set(name, wrapped); window[name] = wrapped;
    }
  }
  window.BeeAdminLifecycle = Object.freeze({register, install,
    diagnostics: () => ({owners: [...hooks.keys()], functions: [...installed.keys()],
      active_refreshes: flights.size, hook_errors: errors, samples: samples.map(row => ({...row}))})});
})();
