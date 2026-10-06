/* One shared presentation controller: no polling, network or business mutations. */
(() => {
  if(window.__beeUiPresentation)return;
  window.__beeUiPresentation=true;document.documentElement.classList.add('ui-enhanced');
  const text=value=>typeof window.translatedCopy==='function'?window.translatedCopy(value):value;
  const closeLabel=()=>typeof window.translatedCopy==='function'?text('بستن'):({fa:'بستن',en:'Close',tr:'Kapat',ar:'إغلاق',es:'Cerrar',it:'Chiudi',de:'Schließen',fr:'Fermer'}[document.documentElement.lang]||'Close');
  window.__beeShowToast=(node,message,error=false,duration=4200)=>{
    clearTimeout(node._timer);clearTimeout(window.__toast);
    node.className='toast'+(error?' error':'');node.setAttribute('role',error?'alert':'status');node.setAttribute('aria-atomic','true');
    const copy=document.createElement('span');copy.className='ui-toast-message';copy.textContent=message;
    const close=document.createElement('button');close.type='button';close.className='ui-toast-close';close.textContent='×';close.setAttribute('aria-label',closeLabel());
    const dismiss=()=>{clearTimeout(node._timer);node.classList.add('hidden');};close.addEventListener('click',dismiss);
    node.replaceChildren(copy,close);node.onkeydown=event=>{if(event.key==='Escape'){event.stopPropagation();dismiss();}};
    if(!error)node._timer=setTimeout(dismiss,duration);
  };
  let tooltip=null,anchor=null,pinned=false,leaveTimer,describedBy=null;
  const trigger=node=>node instanceof Element?node.closest('.info-tip,.info-button,.support-v4-info'):null;
  function hideTip(){clearTimeout(leaveTimer);if(tooltip)tooltip.hidden=true;if(anchor){anchor.setAttribute('aria-expanded','false');if(describedBy===null)anchor.removeAttribute('aria-describedby');else anchor.setAttribute('aria-describedby',describedBy);}anchor=null;pinned=false;describedBy=null;}
  function positionTip(){
    if(!tooltip||tooltip.hidden||!anchor)return;
    const box=anchor.getBoundingClientRect(),tip=tooltip.getBoundingClientRect();
    const left=Math.max(12,Math.min(document.documentElement.dir==='rtl'?box.right-tip.width:box.left,innerWidth-tip.width-12));
    const below=box.bottom+8,candidate=below+tip.height<=innerHeight-12?below:box.top-tip.height-8;
    const top=Math.max(12,Math.min(candidate,innerHeight-tip.height-12));
    tooltip.style.left=`${left}px`;tooltip.style.top=`${top}px`;
  }
  function showTip(button,pin=false){
    const source=button.querySelector('.info-tip-popup')?.textContent||button.dataset.tooltip||button.getAttribute('title');
    if(!source?.trim())return;
    clearTimeout(leaveTimer);
    if(!tooltip){tooltip=document.createElement('div');tooltip.id='beeUiTooltip';tooltip.setAttribute('role','tooltip');tooltip.hidden=true;document.body.appendChild(tooltip);
      tooltip.addEventListener('pointerenter',()=>clearTimeout(leaveTimer));tooltip.addEventListener('pointerleave',()=>{if(!pinned)hideTip();});}
    if(anchor&&anchor!==button)hideTip();
    if(anchor!==button)describedBy=button.getAttribute('aria-describedby');
    anchor=button;pinned=pin;tooltip.textContent=source.trim();tooltip.dir=document.documentElement.dir;tooltip.hidden=false;
    button.setAttribute('aria-describedby',tooltip.id);button.setAttribute('aria-expanded','true');positionTip();
  }
  document.addEventListener('pointerover',event=>{const button=trigger(event.target);if(button&&!button.contains(event.relatedTarget))showTip(button);});
  document.addEventListener('pointerout',event=>{const button=trigger(event.target);if(button&&button===anchor&&!button.contains(event.relatedTarget)&&!pinned)leaveTimer=setTimeout(()=>{if(document.activeElement!==anchor)hideTip();},160);});
  document.addEventListener('focusin',event=>{const button=trigger(event.target);if(button)showTip(button);else if(!tooltip?.contains(event.target))hideTip();});
  document.addEventListener('click',event=>{
    const button=trigger(event.target);
    if(button){event.preventDefault();event.stopImmediatePropagation();if(anchor===button&&pinned)hideTip();else showTip(button,true);}
    else if(!tooltip?.contains(event.target))hideTip();
  },true);
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&anchor){event.preventDefault();event.stopImmediatePropagation();hideTip();}},true);
  window.addEventListener('resize',hideTip);document.addEventListener('scroll',event=>{if(tooltip?.contains(event.target))return;if(anchor&&(document.activeElement===anchor||pinned))positionTip();else hideTip();},true);
  function avatarFallback(image){
    const avatar=image.closest('#sidebarUserAvatar,.sidebar-user-avatar,.sidebar-account-avatar');
    if(!avatar||image.naturalWidth||!image.complete)return;
    const name=document.getElementById('sidebarUserName')?.textContent||document.getElementById('sidebarAccountName')?.textContent||document.getElementById('userName')?.textContent||'?';
    image.hidden=true;avatar.classList.add('ui-avatar-fallback');
    let initials=avatar.querySelector('[data-avatar-initials]');if(!initials){initials=document.createElement('span');initials.dataset.avatarInitials='';initials.setAttribute('aria-hidden','true');avatar.appendChild(initials);}initials.textContent=name.trim().slice(0,2).toUpperCase();
  }
  document.addEventListener('error',event=>{if(event.target instanceof HTMLImageElement)avatarFallback(event.target);},true);
  function enhanceTables(){
    document.querySelectorAll('.view.active .table-wrap,.view.active .schedule-grid-wrap').forEach((wrapper,index)=>{
      wrapper.tabIndex=0;wrapper.setAttribute('role','region');
      const heading=wrapper.closest('.view')?.querySelector('h2');if(heading){if(!heading.id)heading.id=`ui-view-${wrapper.closest('.view').id}`;wrapper.setAttribute('aria-labelledby',heading.id);}
      const table=wrapper.querySelector('table'),columns=table?.tHead?.rows[0]?.cells.length;
      if(columns)wrapper.querySelectorAll('tbody tr').forEach(row=>{if(row.cells.length===1&&row.cells[0].hasAttribute('colspan'))row.cells[0].colSpan=columns;});
    });
    document.querySelectorAll('#sidebarUserAvatar img,.sidebar-user-avatar img,.sidebar-account-avatar img').forEach(avatarFallback);
  }
  for(const name of ['renderPublications','renderSources','renderTopics','renderAssistants','setView','setLanguage']){
    const original=window[name];if(typeof original!=='function')continue;
    window[name]=function(){if(name==='setView'||name==='setLanguage')hideTip();const result=original.apply(this,arguments);enhanceTables();return result;};
  }
  const load=window.loadAll;if(typeof load==='function')window.loadAll=async function(){const result=await load.apply(this,arguments);enhanceTables();return result;};
  enhanceTables();
})();
