
    /* MI-214: support is a dedicated route, never a footer/widget appended to
       another page. Remove only legacy support nodes that escaped their view;
       the support view and its dialog are explicitly protected. */
    (function(){
      const doc=document,content=doc.querySelector('.content');
      const clean=()=>{doc.querySelectorAll('.view:not(#view-support) [id*="support" i],.view:not(#view-support) [class*="support-" i],.view:not(#view-support) [data-support-form],.view:not(#view-support) [data-support-list]').forEach(node=>{if(node.closest('#view-support,#support-ticket-v4-dialog')||node.tagName==='STYLE'||node.tagName==='SCRIPT')return;node.remove()});if(content){[...content.children].filter(node=>node.id&&/support/i.test(node.id)&&node.id!=='view-support').forEach(node=>node.remove())}};
      clean();
      if(content){let queued=false;new MutationObserver(()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;clean()})}).observe(content,{childList:true,subtree:true})}
      window.__researchBeeCleanSupportScope=clean;
    })();
