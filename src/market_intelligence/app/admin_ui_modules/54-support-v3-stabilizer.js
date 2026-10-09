
    /* MI-209: keep the support view idempotent if a late language or data
       refresh recreates its children. */
    (()=>{
      const normalize=()=>{const root=document.getElementById('view-support');if(!root)return;root.classList.add('support-shell','support-v2');root.querySelectorAll('#collectionSettingsCard .admin-ux-owner-badge').forEach(node=>node.remove());root.querySelectorAll('.support-v2-grid').forEach(grid=>{grid.classList.remove('two-col','support-layout')});root.setAttribute('aria-label',state.language==='en'?'Support workspace':'فضای پشتیبانی')};
      normalize();
      const content=document.querySelector('.content');if(content){new MutationObserver(()=>requestAnimationFrame(normalize)).observe(content,{childList:true,subtree:true})}
      window.__researchBeeNormalizeSupport=normalize;
    })();
