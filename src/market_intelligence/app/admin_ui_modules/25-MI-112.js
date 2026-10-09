
    // MI-112: language controls are native dropdowns and English is the
    // first-visit default. Keep the legacy translation function as the single
    // source of copy while synchronizing both selectors after every change.
    (function(){
      const legacySetLanguage=window.setLanguage;
      const sync=()=>document.querySelectorAll('[data-language-select]').forEach(select=>{
        select.value=state.language;
        select.setAttribute('aria-label',state.language==='en'?'Language':'زبان');
      });
      if(typeof legacySetLanguage==='function'){
        window.setLanguage=function(lang){legacySetLanguage(lang);sync()};
      }
      document.querySelectorAll('[data-language-select]').forEach(select=>{
        select.addEventListener('change',()=>window.setLanguage?.(select.value));
      });
      sync();
      const version=document.getElementById('sidebarVersion');
      if(version)version.textContent='v3.30.1';
    })();
