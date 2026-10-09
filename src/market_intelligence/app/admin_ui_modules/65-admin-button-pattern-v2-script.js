
    /* Remove old measured widths rather than measuring and forcing the
       longest sibling width. CSS owns responsive layout and typography. */
    (function(){
      const doc=document;
      const groupSelector='.page-head .actions,.card-actions,.table-actions,.support-v4-actions,.support-v4-status-row';
      const normalize=()=>{doc.querySelectorAll(groupSelector).forEach(group=>{[...group.children].filter(node=>node.matches?.('.btn')).forEach(button=>{button.style.removeProperty('width');button.style.removeProperty('min-width');button.style.removeProperty('flex');delete button.dataset.adminButtonWidth})})};
      window.__researchBeeNormalizeButtons=normalize;
      normalize();
      let queued=false;const schedule=()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;normalize()})};
      window.addEventListener('resize',schedule,{passive:true});window.addEventListener('load',schedule,{once:true});
    })();
