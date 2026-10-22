
    // MI-LOCALE-ATOMIC: every locale change and the first authenticated paint
    // use one serialized commit.  The old page had a chain of locale wrappers
    // plus a whole-document translation observer; each pass could briefly
    // render Persian/English before a later pass selected the requested
    // language.  This controller keeps the shell hidden during reconciliation,
    // renders every view against the same state.language, and then releases it
    // after two animation frames.
    (function(){
      const root=document.documentElement;
      const languages=()=>window.supportedLanguages||{en:{dir:'ltr'},fa:{dir:'rtl'},tr:{dir:'ltr'},ar:{dir:'rtl'},es:{dir:'ltr'},it:{dir:'ltr'},de:{dir:'ltr'},fr:{dir:'ltr'}};
      const pick=value=>languages()[value]?value:'en';
      let serial=0,releaseTimer=0,applying=false,shellReleased=false;
      const updateMeta=language=>{state.language=language;localStorage.setItem('research_bee_language',language);root.lang=language;root.dir=languages()[language]?.dir||'ltr';document.querySelectorAll('[data-language-choice]').forEach(node=>node.classList.toggle('active',node.dataset.languageChoice===language));document.querySelectorAll('[data-language-select]').forEach(node=>{node.value=language;node.setAttribute('aria-label',language==='en'?'Language':'زبان')})};
      const safeCall=(name,...args)=>{const fn=window[name];if(typeof fn!=='function')return;try{return fn(...args)}catch(error){console.warn('locale render failed:',name,error)}};
      const renderPass=()=>{if(applying)return;applying=true;window.__researchBeeLocaleApplying=true;try{[['renderDashboard'],['renderQualityReport',state.feedbackReport||{}],['renderAssistants'],['renderSources'],['renderTopics'],['renderPublications'],['renderTelegram'],['renderOperations'],['renderScheduleGrid'],['renderChannels'],['applyRoleVisibility']].forEach(([name,...args])=>safeCall(name,...args));safeCall('__researchBeeLocalizeAll');safeCall('__researchBeeRunLocaleScrub');safeCall('__researchBeeApplyCatalog');safeCall('__researchBeeNormalizeDigits');safeCall('applyLucideIcons')}finally{applying=false;window.__researchBeeLocaleApplying=false}};
      // Both operations share one transaction. The newest completion must
      // release BOTH classes; otherwise a language switch invalidates the
      // pending shell release and strands an invisible, unclickable page.
      const afterFrames=token=>{requestAnimationFrame(()=>requestAnimationFrame(()=>{if(token===serial){root.classList.remove('locale-pending','locale-switching');shellReleased=true}}))};
      const previous=window.setLanguage||setLanguage;
      if(typeof previous==='function'&&!previous.__atomicLocale){
        const atomic=function(language){const value=pick(language),token=++serial;clearTimeout(releaseTimer);root.classList.add('locale-switching');let result;try{result=previous.call(this,value)}finally{updateMeta(value);renderPass();releaseTimer=setTimeout(()=>afterFrames(token),0)}return result};
        atomic.__atomicLocale=true;window.setLanguage=atomic;setLanguage=atomic;
      }
      // A watchdog may already have exposed the authorized first paint.
      // Later bootstrap completion must reconcile, not hide usable controls
      // again between pointer-down and pointer-up.
      window.__researchBeeReleaseLocale=()=>{const token=++serial;clearTimeout(releaseTimer);if(!shellReleased)root.classList.add('locale-pending');updateMeta(pick(state.language||localStorage.getItem('research_bee_language')||'en'));renderPass();releaseTimer=setTimeout(()=>afterFrames(token),0)};
      // Dynamic views already call renderPass/localizeAll from their render
      // paths, and wrapped render/language events schedule this pass for late
      // panels. Do not install a whole-document observer here: it doubled
      // localization scans and was the source of browser freezes under large
      // publication tables.
    })();
