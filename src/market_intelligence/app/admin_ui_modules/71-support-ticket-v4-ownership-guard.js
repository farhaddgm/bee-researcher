
    /* MI-218: the legacy compatibility layers can still receive a delayed
       locale/data callback after the threaded Support view has mounted.  A
       stale callback must never replace the v4 shell with the old inline
       reply form.  Observe only the Support root and restore the v4 shell
       through its public controller when a legacy render is detected. */
    (function(){
      const reconcile=()=>{
        const root=document.getElementById('view-support'),controller=window.__supportTicketV4;
        if(!root||!controller)return;
        if(!root.querySelector('[data-support-v4-my-list]')){
          root.dataset.supportV4Pending='1';
          controller.render();
          controller.load?.();
        }else if(root.dataset.supportV4Pending){
          delete root.dataset.supportV4Pending;
        }
      };
      reconcile();
      const root=document.getElementById('view-support');
      if(root){let queued=false;new MutationObserver(()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;reconcile()})}).observe(root,{childList:true})}
      window.__researchBeeSupportV4Reconcile=reconcile;
    })();
