/* A single news-window conversation. Opening never calls a paid provider. */
(() => {
  'use strict';
  const i18n=window.BeeNewsChatI18n,reader=window.BeeReader;
  if(!i18n||!reader)return;
  const t=i18n.t,$=id=>document.getElementById(id);
  const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el};
  const btn=(key,fn,primary=false)=>{const b=node('button',t(key),'btn'+(primary?' primary':''));b.dataset.chatKey=key;b.type='button';b.addEventListener('click',fn);return b};
  const field=(key,el)=>{const label=node('label'),text=node('span',t(key));text.dataset.chatKey=key;el.setAttribute('aria-label',t(key));el.dataset.chatLabel=key;label.append(text,el);return label};
  const providerNames={openai:'OpenAI',anthropic:'Anthropic · Claude',google:'Google · Gemini'};
  const requestKey=()=>crypto.randomUUID?.()||'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const n=crypto.getRandomValues(new Uint8Array(1))[0]&15;return(c==='x'?n:(n&3)|8).toString(16)});
  let root,layout,messages,composer,error,status,provider,model,language,sendButton,stopButton,freshButton,tip,insights;
  let seq=0,pid=null,context=null,models=[],cid=null,active=null,events=null,rows=[],pending=false,returnUrl=null,heartbeat=null;
  let statusState={key:'loading'},lastError=null,daily=null,ready=false;
  const windowThreads=new Map();
  async function api(path,options={}){
    const response=await fetch(path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
    const data=await response.json().catch(()=>({}));
    if(!response.ok){const err=new Error(typeof data.detail==='string'?data.detail:'request_failed');err.status=response.status;throw err}return data;
  }
  function messageFor(e){if(e?.status===401)return t('expired');if(e?.status===410)return t('windowExpired');if(e?.message==='context_changed')return t('changed');if(e?.status===429)return t('budget');if(e?.status===403)return t('denied');if(e?.message==='provider_unconfigured'||e?.message==='model_unavailable')return t('unavailable');return t('error')}
  function drawGuide(){tip.replaceChildren(node('span',t('help')),node('span',t('report')),node('span',t('ephemeral')));if(daily!==null)tip.append(node('span',t('daily')+': '+daily));if(context&&!context.complete)tip.append(node('span',t('partial')))}
  function drawStatus(){status.textContent=statusState.key?t(statusState.key):'';status.hidden=!status.textContent}
  function setStatus(key){statusState={key};drawStatus()}
  function clearError(){lastError=null;error.textContent=''}
  const currentModel=()=>models.find(m=>m.key===model.value);
  function controls(){const busy=Boolean(active||pending),disabled=busy||!ready||!context||!currentModel();sendButton.disabled=disabled;stopButton.hidden=!active;provider.disabled=busy;model.disabled=busy;freshButton.disabled=busy||!rows.length;for(const b of insights.querySelectorAll('button'))b.disabled=disabled}
  function eraseServer(id){const news=windowThreads.get(id);if(!news)return;windowThreads.delete(id);api('/user/api/publications/'+news+'/conversations/'+id+'/close',{method:'POST',body:'{}',keepalive:true}).catch(()=>{/* A short server lease handles offline, expired sessions and tab crashes. */})}
  function eraseLocal(){events?.close();events=null;active=null;cid=null;rows=[];composer.value='';delete composer.dataset.signature;delete composer.dataset.key;messages.replaceChildren();error.textContent='';lastError=null}
  function fail(e){lastError=e;error.textContent=messageFor(e);if(e?.status===401||e?.status===410){for(const id of [...windowThreads.keys()])eraseServer(id);eraseLocal();ready=false;context=null;models=[];provider.replaceChildren();model.replaceChildren();error.textContent=messageFor(e);lastError=e;controls()}}
  function availability(enabled){layout.dataset.chatEnabled=String(enabled);root.hidden=!enabled;layout.previousElementSibling.hidden=!enabled;if(!enabled){layout.dataset.mobileTab='news';syncTabs()}}
  function unavailable(key){root.dataset.unavailable='true';availability(true);setStatus(key);controls()}
  function fillModels(key){model.replaceChildren();for(const m of models.filter(m=>m.provider===provider.value)){const o=node('option',m.label);o.value=m.key;model.append(o)}if(key&&[...model.options].some(o=>o.value===key))model.value=key;controls()}
  function resetConversation(){if(cid)eraseServer(cid);eraseLocal();render();controls()}
  function showSegments(){const body=$('dialogBody');body.replaceChildren();for(const seg of context.segments){const p=node('p',seg.text,'chat-segment');p.id='chat-'+seg.id;p.tabIndex=-1;p.dataset.segment=seg.id;body.append(p)}}
  function jump(citation){if(citation.version!==context?.version){setStatus('changed');return}const target=$('chat-'+citation.segment_id);if(!target)return;layout.dataset.mobileTab='news';syncTabs();target.scrollIntoView({block:'nearest',behavior:'auto'});target.focus({preventScroll:true})}
  function render(){
    const pinned=messages.scrollHeight-messages.scrollTop-messages.clientHeight<60;
    messages.replaceChildren();
    if(!rows.length){const empty=node('div',undefined,'chat-empty');empty.append(node('strong',t('emptyTitle')),node('p',t('empty')));messages.append(empty)}
    for(const row of rows){
      const turn=node('article',undefined,'chat-turn');turn.dataset.generation=row.id;
      const question=node('div',row.question,'chat-question');question.dir='auto';const answer=node('div',row.answer,'chat-answer');answer.dir='auto';
      turn.append(question,node('div',providerNames[row.provider]+' · '+row.model,'chat-meta'),answer,node('div',t(row.status==='failed'?'error':row.status),'chat-status'));
      if(row.error_code==='citation_unverified')turn.append(node('p',t('unverified'),'chat-error'));
      else if(row.error_code&&row.status!=='completed')turn.append(node('p',row.status==='unknown'?t('unknown'):t('error'),'chat-error'));
      const actions=node('div',undefined,'chat-actions');
      for(const cite of row.citations||[]){const b=node('button',cite.segment_id,'chat-citation');b.type='button';b.title=cite.quote;b.addEventListener('click',()=>jump(cite));actions.append(b)}
      if(row.answer&&!['queued','running'].includes(row.status)){
        actions.append(btn('copy',async()=>{try{await navigator.clipboard.writeText(row.answer);setStatus('saved')}catch(e){fail(e)}}),btn('note',async()=>{const generation=seq,origin=[t('model')+': '+providerNames[row.provider]+' · '+row.model,t('news')+': '+location.origin+'/user/news/'+pid];if(row.citations?.length)origin.push(t('references')+': '+row.citations.map(c=>c.segment_id+' — '+c.quote).join('\n'));if(await reader.appendNote(row.answer+'\n\n'+origin.join('\n'))){if(generation===seq)setStatus('saved')}else if(generation===seq)fail({})}));
        for(const [key,value] of [['useful',1],['unhelpful',-1]]){const b=btn(key,async()=>{const generation=seq;try{await api('/user/api/chat-messages/'+row.id+'/feedback',{method:'POST',body:JSON.stringify({value})});if(generation!==seq)return;row.feedback=value;render()}catch(e){if(generation===seq)fail(e)}});b.setAttribute('aria-pressed',String(row.feedback===value));actions.append(b)}
      }
      if(['failed','unknown','stopped'].includes(row.status)){const b=btn('retry',()=>{composer.value=row.question;composer.focus();setStatus('retry')});b.disabled=Boolean(active);actions.append(b)}
      turn.append(actions);messages.append(turn);
    }
    if(pinned)messages.scrollTop=messages.scrollHeight;
  }
  function watch(gid,generation){
    events?.close();events=new EventSource('/user/api/chat-generations/'+gid+'/events');const stream=events;
    stream.addEventListener('snapshot',event=>{if(generation!==seq||pid===null)return;const row=JSON.parse(event.data),index=rows.findIndex(r=>r.id===row.id);if(index>=0)rows[index]=row;else rows.push(row);if(!['queued','running'].includes(row.status)){stream.close();if(events===stream)events=null;active=null;setStatus(row.status==='failed'?'error':row.status)}render();controls()});
    stream.addEventListener('access_denied',()=>{stream.close();if(generation===seq)fail({status:401})});
    stream.onerror=()=>{if(generation===seq)fail({});/* Reconnect may GET, but never repeat a paid POST. */};
  }
  async function send(event,intent='question'){
    event?.preventDefault();if(pending||active||!ready||!composer.value.trim()||!context||!currentModel())return;
    const generation=seq,news=pid,question=composer.value.trim(),key=model.value;pending=true;clearError();controls();
    const signature=[pid,context.version,key,language.value,intent,question].join('\u0000');
    if(composer.dataset.signature!==signature){composer.dataset.signature=signature;composer.dataset.key=requestKey()}
    const idempotencyKey=composer.dataset.key;
    try{
      if(!cid){cid=requestKey();windowThreads.set(cid,news)}
      const id=cid;
      // Predetermined UUID + server tombstone make a close-before-ack safe.
      const c=await api('/user/api/publications/'+news+'/conversations',{method:'POST',body:JSON.stringify({model_key:key,conversation_id:id})});
      if(generation!==seq){api('/user/api/publications/'+news+'/conversations/'+id+'/close',{method:'POST',body:'{}',keepalive:true}).catch(()=>{});return}
      if(c.context.version!==context.version)throw {message:'context_changed'};
      const row=await api('/user/api/conversations/'+id+'/messages',{method:'POST',body:JSON.stringify({question,model_key:key,language:language.value,context_version:context.version,intent,idempotency_key:idempotencyKey})});
      if(generation!==seq)return;
      if(!rows.some(r=>r.id===row.id))rows.push(row);active=['queued','running'].includes(row.status)?row.id:null;composer.value='';delete composer.dataset.signature;setStatus(row.status);render();if(active)watch(active,generation);
    }catch(e){if(generation===seq)fail(e)}finally{if(generation===seq){pending=false;controls()}}
  }
  function syncTabs(){layout.previousElementSibling?.querySelectorAll('[data-tab]').forEach(b=>{const selected=b.dataset.tab===layout.dataset.mobileTab;b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1})}
  function build(){
    const deep=document.querySelector('#newsDialog > .deep-reading-layout');if(!deep)return;
    layout=node('div',undefined,'news-study-layout');layout.dataset.mobileTab='news';layout.dataset.chatEnabled='false';deep.before(layout);layout.append(deep);
    const tabs=node('div',undefined,'chat-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label',t('chat'));
    for(const key of ['news','chat']){const b=btn(key,()=>{layout.dataset.mobileTab=key;layout.scrollTop=0;syncTabs()});b.dataset.tab=key;b.setAttribute('role','tab');b.setAttribute('aria-controls',key==='chat'?'newsChat':'dialogBody');tabs.append(b)}
    tabs.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const buttons=[...tabs.querySelectorAll('[data-tab]')],index=buttons.indexOf(document.activeElement),step=(event.key==='ArrowRight'?1:-1)*(document.documentElement.dir==='rtl'?-1:1),next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+step+buttons.length)%buttons.length;buttons[next].click();buttons[next].focus()});layout.before(tabs);
    root=node('section',undefined);root.id='newsChat';root.setAttribute('aria-label',t('chat'));layout.append(root);
    const head=node('div',undefined,'chat-heading'),heading=node('h3',t('chat'));heading.dataset.chatKey='chat';head.append(heading);
    const info=node('button','i','chat-info');info.type='button';info.dataset.chatLabel='help';info.setAttribute('aria-label',t('help'));info.setAttribute('aria-describedby','chat-tip');tip=node('span',undefined,'chat-tip');tip.id='chat-tip';tip.role='tooltip';head.append(info,tip);root.append(head);
    const controlsBox=node('div',undefined,'chat-controls');provider=node('select');model=node('select');language=node('select');
    for(const [code,label] of [['fa','فارسی'],['en','English'],['tr','Türkçe'],['ar','العربية'],['es','Español'],['it','Italiano'],['de','Deutsch'],['fr','Français']]){const o=node('option',label);o.value=code;language.append(o)}language.value=i18n.lang();
    controlsBox.append(field('provider',provider),field('model',model),field('language',language));root.append(controlsBox);
    status=node('p',t('loading'),'chat-status');status.setAttribute('role','status');root.append(status);
    messages=node('div',undefined,'chat-messages');messages.setAttribute('role','log');messages.setAttribute('aria-label',t('chat'));messages.setAttribute('aria-live','off');root.append(messages);
    const suggestions=node('div',undefined,'chat-suggestions');for(const key of ['summary','terms','implications','missing'])suggestions.append(btn(key,()=>{composer.value=t(key);composer.focus()}));root.append(suggestions);
    const form=node('form',undefined,'chat-composer');composer=node('textarea');composer.id='news-chat-question';composer.maxLength=4000;composer.rows=3;composer.dir='auto';form.append(field('ask',composer));
    composer.addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();send()}});
    error=node('p','','chat-error');error.role='alert';form.append(error);
    const sendActions=node('div',undefined,'chat-actions');freshButton=btn('new',()=>{resetConversation();setStatus('');composer.focus()});freshButton.dataset.new='';
    sendButton=node('button',t('send'),'btn primary');sendButton.dataset.chatKey='send';sendButton.type='submit';stopButton=btn('stop',async()=>{if(!active)return;const generation=seq;try{await api('/user/api/chat-generations/'+active+'/cancel',{method:'POST'});if(generation===seq)setStatus('stopped')}catch(e){if(generation===seq)fail(e)}});sendActions.append(freshButton,stopButton,sendButton);form.append(sendActions);form.addEventListener('submit',event=>send(event));root.append(form);
    const privacy=node('p',t('ephemeral'),'chat-privacy-note');privacy.dataset.chatKey='ephemeral';root.append(privacy);
    provider.addEventListener('change',()=>{resetConversation();fillModels();setStatus('brandChange')});
    insights=node('div',undefined,'news-insight-actions');
    for(const intent of ['opportunities','risks']){const b=btn(intent,()=>{if(sendButton.disabled)return;composer.value=t(intent+'Prompt');layout.dataset.mobileTab='chat';layout.scrollTop=0;syncTabs();send(null,intent);composer.focus()});b.dataset.insight=intent;insights.append(b)}
    $('dialogMeta').after(insights);drawGuide();syncTabs();availability(false);
  }
  async function open(){
    const current=reader.current();if(!current.id||!root)return;close(false);const generation=++seq;pid=String(current.id);context=null;models=[];rows=[];pending=false;daily=null;ready=false;root.dataset.unavailable='false';availability(false);clearError();setStatus('loading');composer.value='';render();controls();drawGuide();
    if(!location.pathname.startsWith('/user/news/')){returnUrl=(location.pathname==='/user/login-up'?'/user':location.pathname)+location.search;if(location.pathname==='/user/login-up')history.replaceState(null,'',returnUrl);history.pushState({beeNews:true,returnUrl},'', '/user/news/'+pid+location.search)}
    try{const available=await api('/user/api/chat/models?assistant_id='+encodeURIComponent(current.assistantId));if(generation!==seq)return;if(!available.enabled||!available.models.length){unavailable(available.reason==='chat_disabled'?'featureOff':'unavailable');return}const ctx=await api('/user/api/publications/'+pid+'/chat-context');if(generation!==seq)return;context=ctx;models=available.models;daily=available.daily_requests;provider.replaceChildren();for(const brand of [...new Set(models.map(m=>m.provider))]){const o=node('option',providerNames[brand]);o.value=brand;provider.append(o)}ready=true;fillModels();showSegments();availability(true);drawGuide();setStatus(ctx.complete?'':'partial');controls();
      heartbeat=setInterval(async()=>{const id=cid,currentSeq=seq;if(!id||pending)return;try{await api('/user/api/conversations/'+id+'/heartbeat',{method:'POST',body:'{}'})}catch(e){if(currentSeq===seq&&(e.status===401||e.status===403||e.status===404||e.status===410))fail({status:e.status===410?410:401})}},20000);
    }catch(e){if(generation===seq){unavailable(e.status===403?'permissionNeeded':e.status===404?'denied':e.status===401?'expired':'error');if(e.status===401)fail(e)}}
  }
  function close(navigate=true){
    clearInterval(heartbeat);heartbeat=null;for(const id of [...windowThreads.keys()])eraseServer(id);
    seq++;pending=false;pid=null;ready=false;context=null;models=[];daily=null;
    if(composer){eraseLocal();provider.replaceChildren();model.replaceChildren();drawGuide();setStatus('');controls()}
    if(navigate&&location.pathname.startsWith('/user/news/')){history.replaceState(null,'',returnUrl||'/user'+location.search);returnUrl=null}
  }
  window.__beeNewsChatClose=close;
  build();if(!root)return;
  new MutationObserver(()=>{document.querySelectorAll('[data-chat-key]').forEach(n=>n.textContent=t(n.dataset.chatKey));document.querySelectorAll('[data-chat-label]').forEach(n=>n.setAttribute('aria-label',t(n.dataset.chatLabel)));root.setAttribute('aria-label',t('chat'));drawGuide();drawStatus();if(lastError)error.textContent=messageFor(lastError);render()}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
  new MutationObserver(()=>{const hidden=$('dialogBackdrop').classList.contains('hidden');if(hidden){if(pid)close()}else if(reader.current().id!==pid)open()}).observe($('dialogBackdrop'),{attributes:true,attributeFilter:['class']});
  new MutationObserver(()=>{if($('app').classList.contains('hidden'))close(false)}).observe($('app'),{attributes:true,attributeFilter:['class']});
  window.addEventListener('pagehide',()=>close(false));
  window.addEventListener('popstate',()=>{if(!location.pathname.startsWith('/user/news/')&&!$('dialogBackdrop').classList.contains('hidden'))reader.close()});
  window.addEventListener('pageshow',event=>{if(event.persisted&&!$('dialogBackdrop').classList.contains('hidden'))open()});
  const initialDeepLink=location.pathname.match(/^\/user\/news\/([0-9a-f-]{36})$/i);
  let directStarted=false;
  async function direct(){if(directStarted||!initialDeepLink||$('app').classList.contains('hidden'))return;directStarted=true;try{const item=await api('/user/api/publications/'+initialDeepLink[1]+'/detail');returnUrl='/user'+location.search;reader.open(item)}catch(e){window.toast?.(messageFor(e),true)}}
  new MutationObserver(direct).observe($('app'),{attributes:true,attributeFilter:['class']});direct();
})();
