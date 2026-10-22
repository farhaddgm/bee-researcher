
    // MI-099: make a back-office refresh single-flight. The page has several
    // independent data panels and older handlers captured an earlier loadAll
    // function. A fast double-click (or a click during the initial bootstrap)
    // could therefore start overlapping full refreshes and make the UI appear
    // frozen while duplicate requests competed to repaint it.
    (function(){
      const style=document.createElement('style');const nonce=document.currentScript?.nonce||document.querySelector('script[nonce]')?.nonce;if(nonce){style.nonce=nonce;style.setAttribute('nonce',nonce)}style.textContent='.btn.is-loading{opacity:.68;cursor:wait}.btn.is-loading [data-icon]{animation:researchBeeRefreshSpin .8s linear infinite}@keyframes researchBeeRefreshSpin{to{transform:rotate(360deg)}}';document.head.appendChild(style);
      const activeButtons=()=>[document.getElementById('refreshBtn'),document.getElementById('systemRefreshBtn')].filter(Boolean);
      const setBusy=busy=>activeButtons().forEach(button=>{
        if(busy){
          if(!button.dataset.refreshLabel)button.dataset.refreshLabel=button.getAttribute('aria-label')||button.textContent.trim();
          button.disabled=true;button.setAttribute('aria-busy','true');button.classList.add('is-loading');
        }else{
          button.disabled=false;button.removeAttribute('aria-busy');button.classList.remove('is-loading');
        }
      });
      let activeRefreshes=0;
      window.BeeAdminLifecycle.register('refresh-controls', ['loadAll'], {scoped:false,
        before:()=>{activeRefreshes++;setBusy(true);},
        settled:()=>{activeRefreshes=Math.max(0,activeRefreshes-1);setBusy(activeRefreshes>0);}});
      const runRefresh=event=>{event?.preventDefault();event?.stopPropagation();state.newsViewsLoadedFor=null;state.incidentsLoadedFor=null;return loadAll()};
      const refresh=document.getElementById('refreshBtn'),system=document.getElementById('systemRefreshBtn');
      if(refresh)refresh.onclick=runRefresh;
      if(system)system.onclick=runRefresh;
      window.__researchBeeRefreshBackoffice=runRefresh;
    })();
