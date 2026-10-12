/* Owner-only audio policy. API credentials are deliberately not editable here. */
(() => {
  'use strict';const copy=window.BeeNewsChatI18n;if(!copy)return;const t=copy.t;
  let panel=null,busy=false;
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n};
  const api=async(path,options={})=>{const cookie=document.cookie.split('; ').find(v=>v.startsWith('research_bee_admin_csrf='));const r=await fetch(path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(options.method?{'X-CSRF-Token':cookie?decodeURIComponent(cookie.split('=').slice(1).join('=')):''}:{})}});const data=await r.json();if(!r.ok)throw new Error(t(r.status===401?'expired':r.status===403?'denied':'error'));return data};
  function label(n,key){n.dataset.voiceKey=key;n.textContent=t(key);return n}
  async function sync(){
    if(document.getElementById('app')?.classList.contains('hidden')){panel?.remove();panel=null;return}
    if(panel&&!panel.isConnected)panel=null;
    if(panel||busy||!document.getElementById('view-account')?.classList.contains('active'))return;
    busy=true;
    try{
      const me=await api('/admin/api/me');if(!me.is_owner)return;
      const data=await api('/admin/api/news-voice/policy');if(document.getElementById('app')?.classList.contains('hidden'))return;
      panel=node('section');panel.id='newsVoiceAdmin';panel.className='card section-card';panel.append(label(node('h3'),'voiceAdmin'),label(node('p'),data.configured&&data.server_enabled?'voiceCost':'voiceNotConfigured'));
      const form=node('form'),l=node('label'),editor=node('textarea');editor.rows=14;editor.maxLength=20000;editor.dir='ltr';editor.value=JSON.stringify(data.policy,null,2);editor.setAttribute('aria-label',t('voicePolicyJson'));l.append(label(node('span'),'voicePolicyJson'),editor);form.append(l);
      const save=label(node('button'),'save');save.type='submit';save.className='btn primary';const status=node('p');status.role='status';form.append(save,status);panel.append(form);
      form.addEventListener('submit',async event=>{event.preventDefault();if(save.disabled)return;save.disabled=true;status.textContent='';try{await api('/admin/api/news-voice/policy',{method:'PUT',body:JSON.stringify(JSON.parse(editor.value))});status.textContent=t('saved')}catch(e){status.textContent=e.message===t('expired')||e.message===t('denied')?e.message:t('error')}finally{save.disabled=false}});
      (document.getElementById('accountSecurityPanel')||document.getElementById('view-account')).append(panel);
    }catch(_){/* The account view remains usable if optional voice storage is absent. */}finally{busy=false}
  }
  for(const id of ['app','view-account']){const n=document.getElementById(id);if(n)new MutationObserver(sync).observe(n,{attributes:true,attributeFilter:['class'],childList:id==='view-account',subtree:id==='view-account'})}
  new MutationObserver(()=>{if(panel)for(const n of panel.querySelectorAll('[data-voice-key]'))n.textContent=t(n.dataset.voiceKey)}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});sync();
})();
