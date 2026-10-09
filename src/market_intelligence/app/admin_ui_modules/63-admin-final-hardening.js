
    /* Last, idempotent pass for stale compatibility layers.  It removes only
       explicitly obsolete copy/actions and never touches data controls. */
    (function(){
      // Moving an already-last child with appendChild() still emits a
      // childList mutation.  This normalizer is observed below, so doing that
      // unconditionally created an animation-frame feedback loop: normalize
      // moved controls -> the observer scheduled normalize again -> controls
      // moved again.  Apart from consuming the main thread, that made pointer
      // interactions flaky on wide desktop layouts.  Reorder only when the
      // desired DOM order is actually different.
      function reorderIfNeeded(group,ordered){
        const current=[...group.children];
        if(current.length===ordered.length&&current.every((node,index)=>node===ordered[index]))return;
        const fragment=document.createDocumentFragment();
        ordered.forEach(node=>fragment.appendChild(node));
        group.appendChild(fragment);
      }
      function normalize(){
        const context=document.getElementById('pageContext');if(context)context.remove();
        document.querySelectorAll('button,[role="button"]').forEach(node=>{const value=(node.textContent||'').replace(/\s+/g,' ').trim().toLowerCase();if(value==='view evidence'||value==='نمایش شواهد'||value==='edit content'||value==='ویرایش محتوا')node.remove()});
        document.querySelectorAll('.page-head .actions').forEach(group=>{const seen=new Set();Array.from(group.children).forEach(node=>{const value=(node.textContent||'').replace(/\s+/g,' ').trim().toLowerCase();if(!value)return;if(seen.has(value))node.remove();else seen.add(value)})});
        /* Keep action priority deterministic even when buttons are injected
           after the initial render (sandbox/share/preview controls).  The
           assistant page has a deliberate three-step order; other groups put
           their primary action first and preserve the relative order of the
           neutral/destructive actions. */
        const assistantGroup=document.querySelector('#view-assistants .page-head .actions');
        if(assistantGroup){const preferred=['newAssistantBtn','sandboxAssistantBtn','quickAssistantBtn'].map(id=>document.getElementById(id)).filter(node=>node&&node.parentElement===assistantGroup);const rest=[...assistantGroup.children].filter(node=>!preferred.includes(node));const ordered=[...preferred,...rest],primary=ordered.filter(node=>node.classList.contains('primary')),neutral=ordered.filter(node=>!primary.includes(node));reorderIfNeeded(assistantGroup,[...neutral,...primary])}
        document.querySelectorAll('.page-head .actions').forEach(group=>{const children=[...group.children],primary=children.filter(node=>node.classList.contains('primary')),rest=children.filter(node=>!primary.includes(node));reorderIfNeeded(group,[...rest,...primary])});
        document.querySelectorAll('.card-actions').forEach(group=>{const children=[...group.children],primary=children.filter(node=>node.classList.contains('primary')),rest=children.filter(node=>!primary.includes(node));if(primary.length)reorderIfNeeded(group,[...rest,...primary])});
        window.__researchBeeNormalizeButtons?.();
        const support=document.getElementById('view-support');if(support){support.classList.add('support-final');support.removeAttribute('aria-busy')}
      }
      window.__researchBeeFinalHardening=normalize;normalize();
      let queued=false;const schedule=()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;normalize()})};
      // Observe only the authenticated app root.  Watching document.body made
      // every toast/modal mutation trigger a full-page normalization pass.
      const mutationRoot=document.getElementById('app')||document.body;
      new MutationObserver(schedule).observe(mutationRoot,{subtree:true,childList:true});
    })();
