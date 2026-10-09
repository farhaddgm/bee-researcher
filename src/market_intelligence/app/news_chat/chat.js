/* Per-news private study surface. No request to an AI is made on opening. */
(() => {
  'use strict';
  const i18n=window.BeeNewsChatI18n,reader=window.BeeReader;
  if(!i18n||!reader)return;
  const t=i18n.t,$=id=>document.getElementById(id);
  const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el};
  const btn=(key,fn,primary=false)=>{const b=node('button',t(key),'btn'+(primary?' primary':''));b.dataset.chatKey=key;b.type='button';b.addEventListener('click',fn);return b};
  const field=(key,el)=>{const label=node('label'),text=node('span',t(key));text.dataset.chatKey=key;el.setAttribute('aria-label',t(key));el.dataset.chatLabel=key;label.append(text,el);return label};
  const providerNames={openai:'OpenAI',anthropic:'Anthropic · Claude',google:'Google · Gemini'};
  const requestKey=()=>crypto.randomUUID?.()||Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
  let root,layout,messages,composer,error,status,provider,model,language,thread,sendButton,stopButton,olderButton;
  let seq=0,pid=null,context=null,models=[],threads=[],cid=null,active=null,events=null,rows=[],cursor=null,selection=null,pending=false,returnUrl=null,loadingThread=false,threadVersion=null;
  let statusState={key:'loading',detail:null},lastError=null;
  const drafts=new Map();
  async function api(path,options={}){
    const response=await fetch(path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
    const data=await response.json().catch(()=>({}));
    if(!response.ok){const err=new Error(typeof data.detail==='string'?data.detail:'request_failed');err.status=response.status;throw err}return data;
  }
  function messageFor(e){if(e?.status===401)return t('expired');if(e?.message==='context_changed')return t('changed');if(e?.status===429)return t('budget');if(e?.status===403)return t('denied');if(e?.message==='provider_unconfigured'||e?.message==='model_unavailable')return t('unavailable');return t('error')}
  function drawStatus(){status.textContent=statusState.key?t(statusState.key):'';if(statusState.key==='selection')status.textContent+=': '+statusState.detail;if(statusState.key==='report'&&statusState.detail){status.textContent+=' · '+t('daily')+': '+statusState.detail.daily;if(statusState.detail.partial)status.textContent+=' · '+t('partial')}}
  function setStatus(key,detail=null){statusState={key,detail};drawStatus()}
  function clearError(){lastError=null;error.textContent=''}
  function fail(e){lastError=e;error.textContent=messageFor(e);if(e?.status===401){events?.close();events=null;active=null;cid=null;context=null;threadVersion=null;models=[];threads=[];rows=[];cursor=null;selection=null;provider.replaceChildren();model.replaceChildren();thread.replaceChildren();messages.replaceChildren();composer.value='';drafts.clear();controls()}}
  const currentModel=()=>models.find(m=>m.key===model.value);
  function controls(){const busy=Boolean(active||pending||loadingThread);sendButton.disabled=busy||!context||!currentModel()||Boolean(cid&&threadVersion!==context.version);stopButton.hidden=!active;provider.disabled=busy;model.disabled=busy;thread.disabled=busy;root.querySelector('[data-new]').disabled=busy;root.querySelector('[data-delete]').disabled=busy||!cid;olderButton.hidden=!cursor;olderButton.disabled=busy}
  function availability(enabled){layout.dataset.chatEnabled=String(enabled);root.hidden=!enabled;layout.previousElementSibling.hidden=!enabled;$('chat-selection').hidden=!enabled;if(!enabled){layout.dataset.mobileTab='news';syncTabs()}}
  function fillModels(key){model.replaceChildren();for(const m of models.filter(m=>m.provider===provider.value)){const o=node('option',m.label);o.value=m.key;model.append(o)}if(key&&[...model.options].some(o=>o.value===key))model.value=key;controls()}
  function resetConversation(){events?.close();events=null;cid=null;threadVersion=null;rows=[];cursor=null;selection=null;delete composer.dataset.signature;thread.value='';render();controls()}
  function renderThreads(){thread.replaceChildren();const empty=node('option',t('new'));empty.value='';thread.append(empty);const format=new Intl.DateTimeFormat(i18n.lang(),{dateStyle:'short',timeStyle:'short'});for(const c of threads){const o=node('option',providerNames[c.provider]+' · '+format.format(new Date(c.created_at)));o.value=c.id;thread.append(o)}thread.value=cid||''}
  function showSegments(){const body=$('dialogBody');body.replaceChildren();for(const seg of context.segments){const p=node('p',seg.text,'chat-segment');p.id='chat-'+seg.id;p.tabIndex=-1;p.dataset.segment=seg.id;body.append(p)}}
  function jump(citation){if(citation.version!==context?.version){setStatus('changed');return}const target=$('chat-'+citation.segment_id);if(!target)return;layout.dataset.mobileTab='news';syncTabs();target.scrollIntoView({block:'nearest',behavior:'auto'});target.focus({preventScroll:true})}
  function render(){
    const pinned=messages.scrollHeight-messages.scrollTop-messages.clientHeight<60;
    messages.replaceChildren();
    if(!rows.length)messages.append(node('p',t('empty'),'chat-status'));
    for(const row of rows){
      const turn=node('article',undefined,'chat-turn');turn.dataset.generation=row.id;
      const question=node('div',row.question,'chat-question');question.dir='auto';const answer=node('div',row.answer,'chat-answer');answer.dir='auto';
      turn.append(question,node('div',providerNames[row.provider]+' · '+row.model,'chat-meta'),answer,node('div',t(row.status==='failed'?'error':row.status),'chat-status'));
      if(row.error_code==='citation_unverified')turn.append(node('p',t('unverified'),'chat-error'));
      else if(row.error_code&&row.status!=='completed')turn.append(node('p',row.status==='unknown'?t('unknown'):t('error'),'chat-error'));
      const actions=node('div',undefined,'chat-actions');
      for(const cite of row.citations||[]){const b=node('button',cite.segment_id,'chat-citation');b.type='button';b.title=cite.quote;b.addEventListener('click',()=>jump(cite));actions.append(b)}
      if(row.answer&& !['queued','running'].includes(row.status)){
        actions.append(btn('copy',async()=>{try{await navigator.clipboard.writeText(row.answer);setStatus('saved')}catch(e){fail(e)}}),btn('note',async()=>{const origin=[t('model')+': '+providerNames[row.provider]+' · '+row.model,t('news')+': '+location.origin+'/user/news/'+pid];if(row.citations?.length)origin.push(t('references')+': '+row.citations.map(c=>c.segment_id+' — '+c.quote).join('\n'));if(await reader.appendNote(row.answer+'\n\n'+origin.join('\n')))setStatus('saved');else fail({})}));
        for(const [key,value] of [['useful',1],['unhelpful',-1]]){const b=btn(key,async()=>{try{await api('/user/api/chat-messages/'+row.id+'/feedback',{method:'POST',body:JSON.stringify({value})});row.feedback=value;render()}catch(e){fail(e)}});b.setAttribute('aria-pressed',String(row.feedback===value));actions.append(b)}
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
    stream.onerror=()=>{if(generation===seq){fail({});/* EventSource may reconnect, but never re-POST a question. */}};
  }
  async function loadThread(id){
    const generation=seq;loadingThread=true;controls();clearError();
    try{const data=await api('/user/api/conversations/'+id+'/messages');if(generation!==seq)return;const c=threads.find(c=>c.id===id),m=models.find(m=>m.provider===c?.provider);if(!m)throw {status:403};cid=id;threadVersion=data.context.version;provider.value=m.provider;fillModels(data.messages.at(-1)?.model_key||m.key);rows=data.messages;cursor=data.older_before;thread.value=id;
      setStatus(data.context.version===context.version?'report':'changed');render();active=rows.find(r=>['queued','running'].includes(r.status))?.id||null;if(active)watch(active,generation);
    }catch(e){if(generation===seq)fail(e)}finally{if(generation===seq){loadingThread=false;controls()}}
  }
  async function send(event){
    event?.preventDefault();if(pending||active||loadingThread||!composer.value.trim()||!context||!currentModel()||Boolean(cid&&threadVersion!==context.version))return;
    const generation=seq,question=composer.value.trim(),key=model.value;pending=true;clearError();controls();
    // Keep the idempotency key for a failed/ambiguous HTTP acknowledgement.
    const signature=[pid,context.version,key,language.value,selection||'',question].join('\u0000');
    if(composer.dataset.signature!==signature){composer.dataset.signature=signature;composer.dataset.key=requestKey()}
    const idempotencyKey=composer.dataset.key;
    try{
      if(!cid){const c=await api('/user/api/publications/'+pid+'/conversations',{method:'POST',body:JSON.stringify({model_key:key})});if(generation!==seq)return;cid=c.id;threadVersion=c.context.version;threads.unshift({id:cid,provider:c.provider,created_at:new Date().toISOString(),context_version:c.context.version});renderThreads()}
      const row=await api('/user/api/conversations/'+cid+'/messages',{method:'POST',body:JSON.stringify({question,model_key:key,language:language.value,context_version:context.version,selected_segment:selection,idempotency_key:idempotencyKey})});
      if(generation!==seq)return;
      if(!rows.some(r=>r.id===row.id))rows.push(row);active=['queued','running'].includes(row.status)?row.id:null;composer.value='';drafts.delete(pid);delete composer.dataset.signature;selection=null;setStatus(row.status);render();if(active)watch(active,generation);
    }catch(e){if(generation===seq)fail(e)}finally{if(generation===seq){pending=false;controls()}}
  }
  function syncTabs(){root.parentElement.previousElementSibling?.querySelectorAll('[data-tab]').forEach(b=>{const selected=b.dataset.tab===layout.dataset.mobileTab;b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1})}
  function build(){
    const deep=document.querySelector('#newsDialog > .deep-reading-layout');if(!deep)return;
    layout=node('div',undefined,'news-study-layout');layout.dataset.mobileTab='news';layout.dataset.chatEnabled='false';deep.before(layout);layout.append(deep);
    const tabs=node('div',undefined,'chat-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label',t('chat'));
    for(const key of ['news','chat']){const b=btn(key,()=>{layout.dataset.mobileTab=key;layout.scrollTop=0;syncTabs()});b.dataset.tab=key;b.setAttribute('role','tab');b.setAttribute('aria-controls',key==='chat'?'newsChat':'dialogBody');tabs.append(b)}
    tabs.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const buttons=[...tabs.querySelectorAll('[data-tab]')],index=buttons.indexOf(document.activeElement),step=(event.key==='ArrowRight'?1:-1)*(document.documentElement.dir==='rtl'?-1:1),next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+step+buttons.length)%buttons.length;buttons[next].click();buttons[next].focus()});layout.before(tabs);
    root=node('section',undefined);root.id='newsChat';root.setAttribute('aria-label',t('chat'));layout.append(root);
    const head=node('div',undefined,'chat-heading'),heading=node('h3',t('chat'));heading.dataset.chatKey='chat';head.append(heading);const info=node('button','i','chat-info');info.type='button';info.dataset.chatLabel='help';info.setAttribute('aria-label',t('help'));info.setAttribute('aria-describedby','chat-tip');const tip=node('span',t('help'),'chat-tip');tip.dataset.chatKey='help';tip.id='chat-tip';tip.role='tooltip';head.append(info,tip);root.append(head);
    const controlsBox=node('div',undefined,'chat-controls');provider=node('select');model=node('select');language=node('select');thread=node('select');
    for(const [code,label] of [['fa','فارسی'],['en','English'],['tr','Türkçe'],['ar','العربية'],['es','Español'],['it','Italiano'],['de','Deutsch'],['fr','Français']]){const o=node('option',label);o.value=code;language.append(o)}language.value=i18n.lang();
    controlsBox.append(field('provider',provider),field('model',model),field('language',language),field('thread',thread));root.append(controlsBox);
    const actions=node('div',undefined,'chat-actions'),fresh=btn('new',()=>{resetConversation();setStatus('empty')}),remove=btn('remove',async()=>{if(!cid||!confirm(t('confirmDelete')))return;const generation=seq,id=cid;try{await api('/user/api/conversations/'+id,{method:'DELETE'});if(generation!==seq)return;threads=threads.filter(c=>c.id!==id);resetConversation();renderThreads();setStatus('saved')}catch(e){fail(e)}});fresh.dataset.new='';remove.dataset.delete='';actions.append(fresh,remove);root.append(actions);
    status=node('p',t('loading'),'chat-status');status.setAttribute('role','status');root.append(status);
    messages=node('div',undefined,'chat-messages');messages.setAttribute('role','log');messages.setAttribute('aria-label',t('thread'));/* Avoid announcing the entire growing answer for each token. */messages.setAttribute('aria-live','off');root.append(messages);
    olderButton=btn('older',async()=>{if(!cid||!cursor||loadingThread||active||pending)return;const generation=seq;loadingThread=true;controls();try{const data=await api('/user/api/conversations/'+cid+'/messages?before='+cursor);if(generation!==seq)return;const previousHeight=messages.scrollHeight,previousTop=messages.scrollTop;const existing=new Set(rows.map(r=>r.id));rows=[...data.messages.filter(r=>!existing.has(r.id)),...rows];cursor=data.older_before;render();messages.scrollTop=previousTop+messages.scrollHeight-previousHeight}catch(e){if(generation===seq)fail(e)}finally{if(generation===seq){loadingThread=false;controls()}}});root.append(olderButton);
    const suggestions=node('div',undefined,'chat-suggestions');for(const key of ['summary','terms','implications','missing'])suggestions.append(btn(key,()=>{composer.value=t(key);composer.focus()}));root.append(suggestions);
    const form=node('form',undefined,'chat-composer');composer=node('textarea');composer.id='news-chat-question';composer.maxLength=4000;composer.rows=3;composer.dir='auto';form.append(field('ask',composer));
    composer.addEventListener('input',()=>drafts.set(pid,composer.value));composer.addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();send()}});
    error=node('p','','chat-error');error.role='alert';form.append(error);const sendActions=node('div',undefined,'chat-actions');sendButton=node('button',t('send'),'btn primary');sendButton.dataset.chatKey='send';sendButton.type='submit';stopButton=btn('stop',async()=>{if(!active)return;try{await api('/user/api/chat-generations/'+active+'/cancel',{method:'POST'});setStatus('stopped')}catch(e){fail(e)}});sendActions.append(stopButton,sendButton);form.append(sendActions);form.addEventListener('submit',send);root.append(form);
    provider.addEventListener('change',()=>{resetConversation();fillModels();setStatus('brandChange')});thread.addEventListener('change',()=>{if(thread.value)loadThread(thread.value);else resetConversation()});
    const selectedParagraph=()=>{const s=window.getSelection(),element=n=>(n?.nodeType===Node.ELEMENT_NODE?n:n?.parentElement)?.closest('[data-segment]'),start=element(s?.anchorNode);return s?.toString().trim()&&start&&start===element(s.focusNode)&&$('dialogBody').contains(start)?start:null};
    const choose=btn('select',()=>{const element=selectedParagraph();if(!element)return;selection=element.dataset.segment;setStatus('selection',element.textContent.slice(0,160));layout.dataset.mobileTab='chat';syncTabs();composer.focus()});choose.id='chat-selection';choose.disabled=true;
    // A pointer press on the action must not collapse the report selection
    // before its click handler reads it. Keyboard activation stays native.
    choose.addEventListener('pointerdown',event=>{if(selectedParagraph())event.preventDefault()});document.addEventListener('selectionchange',()=>{choose.disabled=!selectedParagraph()});deep.prepend(choose);syncTabs();availability(false);
  }
  async function open(){
    const current=reader.current();if(!current.id||!root)return;close(false);const generation=++seq;pid=String(current.id);context=null;models=[];threads=[];cid=null;threadVersion=null;rows=[];cursor=null;selection=null;pending=false;loadingThread=false;availability(false);clearError();setStatus('loading');composer.value=drafts.get(pid)||'';render();controls();
    if(!location.pathname.startsWith('/user/news/')){returnUrl=(location.pathname==='/user/login-up'?'/user':location.pathname)+location.search;if(location.pathname==='/user/login-up')history.replaceState(null,'',returnUrl);history.pushState({beeNews:true,returnUrl},'', '/user/news/'+pid+location.search)}
    try{const available=await api('/user/api/chat/models?assistant_id='+encodeURIComponent(current.assistantId));if(generation!==seq||!available.enabled||!available.models.length)return;const [ctx,list]=await Promise.all([api('/user/api/publications/'+pid+'/chat-context'),api('/user/api/publications/'+pid+'/conversations')]);if(generation!==seq)return;context=ctx;models=available.models;threads=list.conversations;provider.replaceChildren();for(const brand of [...new Set(models.map(m=>m.provider))]){const o=node('option',providerNames[brand]);o.value=brand;provider.append(o)}fillModels();renderThreads();showSegments();availability(true);setStatus('report',{daily:available.daily_requests,partial:!ctx.complete});if(threads.length&&models.some(m=>m.provider===threads[0].provider))await loadThread(threads[0].id);controls();
    }catch(e){if(generation===seq){setStatus(null);if(![403,404].includes(e.status))availability(true);fail(e)}}
  }
  function close(navigate=true){
    if(pid&&composer)drafts.set(pid,composer.value);events?.close();events=null;
    if(active){api('/user/api/chat-generations/'+active+'/cancel',{method:'POST'}).catch(()=>{});active=null}
    seq++;pending=false;pid=null;
    if(navigate&&location.pathname.startsWith('/user/news/')){history.replaceState(null,'',returnUrl||'/user'+location.search);returnUrl=null}
  }
  window.__beeNewsChatClose=close;
  build();if(!root)return;
  new MutationObserver(()=>{document.querySelectorAll('[data-chat-key]').forEach(n=>n.textContent=t(n.dataset.chatKey));document.querySelectorAll('[data-chat-label]').forEach(n=>n.setAttribute('aria-label',t(n.dataset.chatLabel)));root.setAttribute('aria-label',t('chat'));drawStatus();if(lastError)error.textContent=messageFor(lastError);renderThreads();render()}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
  new MutationObserver(()=>{const hidden=$('dialogBackdrop').classList.contains('hidden');if(hidden){if(pid)close()}else if(reader.current().id!==pid)open()}).observe($('dialogBackdrop'),{attributes:true,attributeFilter:['class']});
  new MutationObserver(()=>{if($('app').classList.contains('hidden')){close(false);drafts.clear();rows=[];messages.replaceChildren();composer.value=''}}).observe($('app'),{attributes:true,attributeFilter:['class']});
  window.addEventListener('popstate',()=>{if(!location.pathname.startsWith('/user/news/')&&!$('dialogBackdrop').classList.contains('hidden'))reader.close()});
  // The deep link is fetched through the same server-side project ACL as the feed.
  const initialDeepLink=location.pathname.match(/^\/user\/news\/([0-9a-f-]{36})$/i);
  let directStarted=false;
  async function direct(){if(directStarted||!initialDeepLink||$('app').classList.contains('hidden'))return;directStarted=true;try{const item=await api('/user/api/publications/'+initialDeepLink[1]+'/detail');returnUrl='/user'+location.search;reader.open(item)}catch(e){window.toast?.(messageFor(e),true)}}
  new MutationObserver(direct).observe($('app'),{attributes:true,attributeFilter:['class']});direct();
})();
