
    // MI-112: language controls are native dropdowns and English is the
    // first-visit default. Keep the legacy translation function as the single
    // source of copy while synchronizing both selectors after every change.
    (function(){
      const sync=()=>document.querySelectorAll('[data-language-select]').forEach(select=>{
        select.value=state.language;
        select.setAttribute('aria-label',state.language==='en'?'Language':'زبان');
      });
      window.BeeAdminLifecycle.register('language-selectors', ['setLanguage'], {after:sync});
      document.querySelectorAll('[data-language-select]').forEach(select=>{
        select.addEventListener('change',()=>window.setLanguage?.(select.value));
      });
      sync();
      const version=document.getElementById('sidebarVersion');
      if(version)version.textContent='v3.30.1';
    })();
