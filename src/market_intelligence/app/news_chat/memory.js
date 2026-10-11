/* Saved conversations are loaded from the server for the selected workspace. */
(() => {
  'use strict';
  const reader=window.BeeReader,i18n=window.BeeNewsChatI18n;
  if(!reader||!i18n)return;
  const directMemory=new URLSearchParams(location.search).get('conversation');
  const t=i18n.t,$=id=>document.getElementById(id),node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n};
  const label=(n,key)=>{n.dataset.chatKey=key;n.textContent=t(key);return n};
  const button=(key,action)=>{const n=label(node('button',undefined,'btn'),key);n.type='button';n.addEventListener('click',action);return n};
  let seq=0,workspace=null,cursor=null,busy=false;let voiceLibrary=null;
  const panel=node('details',undefined,'project-chat-memory');panel.id='projectChatMemory';
  panel.append(label(node('summary'),'projectMemory'));
  const project=node('p',undefined,'chat-meta'),status=node('p',undefined,'chat-status'),items=node('div',undefined,'memory-items');status.role='status';
  const more=button('older',()=>load(true)),refresh=button('refreshMemory',()=>load());more.hidden=true;
  const searchForm=node('form',undefined,'memory-search'),filters={};
  for(const [key,type,param] of [['memorySearch','search','q'],['modelFilter','text','model'],['fromDate','date','after_date'],['toDate','date','until_date']]){const l=node('label'),input=node('input');input.type=type;if(type!=='date')input.maxLength=120;l.append(label(node('span'),key),input);searchForm.append(l);filters[param]=input}
  const search=label(node('button',undefined,'btn'),'search');search.type='submit';const reset=button('reset',()=>{searchForm.reset();load()});searchForm.append(search,reset);searchForm.addEventListener('submit',event=>{event.preventDefault();load()});
  panel.append(project,status,searchForm,refresh,items,more);$('feedPage')?.prepend(panel);
  const sidebar=button('projectMemory',()=>{if(location.pathname.replace(/\/+$/,'').endsWith('/user/settings')){location.assign('/user?memory=1');return}if($('sidebar')?.classList.contains('open'))$('mobileMenuButton')?.click();panel.open=true;panel.scrollIntoView({block:'start'});load()});sidebar.className='sidebar-item';sidebar.title=t('projectMemory');
  const mark=node('span','◈','sidebar-icon'),copy=label(node('span'),'projectMemory');mark.setAttribute('aria-hidden','true');sidebar.removeAttribute('data-chat-key');sidebar.replaceChildren(mark,copy);
  $('sidebar')?.querySelector('.sidebar-spacer')?.before(sidebar);
  async function api(path,options={}){
    const r=await fetch(path,{credentials:'same-origin',...options});const data=await r.json().catch(()=>({}));
    if(!r.ok){const e=new Error(typeof data.detail==='string'?data.detail:'request_failed');e.status=r.status;throw e}return data;
  }
  function clear(){seq++;workspace=null;cursor=null;busy=false;panel.querySelectorAll('audio').forEach(a=>a.pause());items.replaceChildren();voiceLibrary?.remove();voiceLibrary=null;more.hidden=true;status.textContent='';project.textContent=''}
  async function expand(entry,body,trigger){
    if(!body.hidden){body.hidden=true;body.querySelectorAll('audio').forEach(a=>a.pause());trigger.setAttribute('aria-expanded','false');return}
    body.hidden=false;trigger.setAttribute('aria-expanded','true');body.replaceChildren();
    const generation=seq;let before=null,loading=false;
    const messages=node('div',undefined,'memory-messages');body.append(messages);
    const previous=button('older',()=>historyPage());previous.hidden=true;body.append(previous);
    async function historyPage(){
      if(loading)return;loading=true;previous.disabled=true;
      try{
        const data=await api('/user/api/conversations/'+entry.id+'/messages'+(before?'?before='+before:''));
        if(generation!==seq||!body.isConnected)return;
        const fragment=document.createDocumentFragment();
        for(const row of data.messages){const turn=node('article',undefined,'chat-turn');const question=node('p',row.question,'chat-question'),answer=node('p',row.answer,'chat-answer');question.dir=answer.dir='auto';turn.append(question,node('p',row.provider+' · '+row.model,'chat-meta'),answer);for(const citation of row.citations||[])turn.append(node('p',citation.segment_id+' · '+citation.quote,'chat-meta'));fragment.append(turn)}
        messages.prepend(fragment);before=data.older_before;previous.hidden=!before;
      }catch(e){if(generation===seq){messages.replaceChildren(node('p',t(e.status===401?'expired':e.status===403||e.status===404?'denied':'error'),'chat-error'))}}
      finally{loading=false;previous.disabled=false}
    }
    await historyPage();try{await window.BeeNewsVoice?.attachMemory(body,entry.id,key=>status.textContent=t(key))}catch(_){status.textContent=t('voiceError')}
  }
  function card(entry){
    const el=node('article',undefined,'memory-card');el.dataset.memory=entry.id;
    const heading=node('h3',entry.title);heading.dir='auto';el.append(heading,node('p',entry.provider+' · '+new Intl.DateTimeFormat(i18n.lang(),{dateStyle:'medium',timeStyle:'short'}).format(new Date(entry.saved_at)),'chat-meta'));
    const body=node('div');body.hidden=true;body.id='memory-'+entry.id;
    const view=button('viewConversation',()=>expand(entry,body,view));view.setAttribute('aria-expanded','false');view.setAttribute('aria-controls',body.id);
    const link=label(node('a',undefined,'btn'),'sourceNews');link.href='/user/news/'+entry.publication_id;
    const remove=button('removeMemory',async()=>{const generation=seq;remove.disabled=true;try{try{await api('/user/api/conversations/'+entry.id+'/memory',{method:'DELETE'})}catch(e){if(e.message!=='audio_removal_confirmation_required'||!window.confirm(t('audioUnsaveConfirm')))throw e;await api('/user/api/conversations/'+entry.id+'/memory?remove_audio=true',{method:'DELETE'})}if(generation===seq){el.remove();if(!items.children.length)status.textContent=t('memoryEmpty')}}catch(e){if(generation===seq)status.textContent=t('error')}finally{remove.disabled=false}});
    const actions=node('div',undefined,'chat-actions');actions.append(view,link,remove);el.append(actions,body);return el;
  }
  async function load(older=false){
    if($('app')?.classList.contains('hidden')){clear();return}
    const selected=reader.workspace();if(!selected.id){clear();return}
    if(!older){clear();workspace=selected.id;project.textContent=selected.name;voiceLibrary=node('div');panel.append(voiceLibrary);window.BeeNewsVoice?.gallery(voiceLibrary,workspace)}
    if(busy||workspace!==selected.id||(older&&!cursor))return;
    const generation=seq;busy=true;refresh.disabled=more.disabled=true;status.textContent=t('loading');
    try{
      const params=new URLSearchParams();for(const [key,input] of Object.entries(filters))if(input.value.trim())params.set(key,input.value.trim());if(older)params.set('before',cursor);
      const data=await api('/user/api/assistants/'+workspace+'/memory?'+params);
      if(generation!==seq)return;
      for(const entry of data.memories)items.append(card(entry));cursor=data.older_before;more.hidden=!cursor;
      status.textContent=items.children.length?t('memoryHelp'):t('memoryEmpty');
      const direct=directMemory;
      if(!older&&direct&&/^[0-9a-f-]{36}$/i.test(direct)){
        const entry=await api('/user/api/conversations/'+direct+'/memory-reference');if(generation!==seq)return;
        if(entry.assistant_id===workspace){let target=items.querySelector('[data-memory="'+direct+'"]');if(!target){target=card(entry);items.prepend(target)}const trigger=target.querySelector('button[aria-controls]');if(trigger&&trigger.getAttribute('aria-expanded')!=='true')trigger.click()}
      }
    }catch(e){if(generation===seq){items.replaceChildren();more.hidden=true;status.textContent=t(e.status===401?'expired':e.status===403||e.status===404?'denied':'error')}}
    finally{if(generation===seq){busy=false;refresh.disabled=more.disabled=false}}
  }
  panel.addEventListener('toggle',()=>{if(panel.open)load()});
  $('assistantSelect')?.addEventListener('change',()=>{clear();if(panel.open)load()});
  if($('assistantSelect'))new MutationObserver(()=>{if(panel.open&&workspace!==reader.workspace().id)load()}).observe($('assistantSelect'),{childList:true});
  window.addEventListener('bee:memory-saved',()=>{if(panel.open)load()});
  let appWasHidden=$('app').classList.contains('hidden');
  new MutationObserver(()=>{const hidden=$('app').classList.contains('hidden');if(hidden===appWasHidden)return;appWasHidden=hidden;if(hidden)clear();else if(panel.open)load()}).observe($('app'),{attributes:true,attributeFilter:['class']});
  new MutationObserver(()=>{sidebar.title=t('projectMemory');panel.querySelectorAll('[data-chat-key]').forEach(n=>n.textContent=t(n.dataset.chatKey))}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
  if(new URLSearchParams(location.search).get('memory')==='1')panel.open=true;
})();
