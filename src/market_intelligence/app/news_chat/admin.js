/* Owner-only, metadata-only administration. No provider key or chat transcript. */
(() => {
  'use strict';
  const i18n=window.BeeNewsChatI18n;if(!i18n)return;const t=i18n.t;
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n};
  const translated=(tag,key,cls)=>{const n=node(tag,t(key),cls);n.dataset.chatAdminKey=key;return n};
  const button=(key,action)=>{const b=translated('button',key,'btn');b.type='button';b.addEventListener('click',action);return b};
  const csrf=()=>{const v=document.cookie.split('; ').find(v=>v.startsWith('research_bee_admin_csrf='));return v?decodeURIComponent(v.slice(v.indexOf('=')+1)):''};
  async function api(path,options={}){const r=await fetch(path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(options.method?{'X-CSRF-Token':csrf()}:{}),...(options.headers||{})}});const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(t(r.status===401?'expired':r.status===403?'denied':'error'));return data}
  let panel=null,busy=false,policy=null,ready={},localizers=[];
  const input=(type,value)=>{const n=node('input');n.type=type;if(type==='checkbox')n.checked=Boolean(value);else n.value=value??'';return n};
  function field(parent,key,control){const label=node('label');label.append(translated('span',key));control.setAttribute('aria-label',t(key));control.dataset.chatAdminLabel=key;label.append(control);parent.append(label);return control}
  const number=(parent,key,value,min,max,step)=>{const n=input('number',value);n.required=true;n.min=min;n.max=max;n.step=step;return field(parent,key,n)};
  function build(data){
    const host=document.getElementById('accountSecurityPanel')||document.getElementById('view-account');if(!host)return;
    localizers=[];panel=node('section',undefined,'card section-card');panel.id='newsChatAdmin';panel.dataset.locale=i18n.lang();host.append(panel);
    const head=node('div',undefined,'chat-heading');head.append(translated('h3','settings'),translated('span','owner','accounts-status is-owner'));panel.append(head,translated('p','scope','accounts-help'),translated('p','setup','accounts-help'));if(!data.server_enabled)panel.append(translated('p','serverOff','accounts-help'));
    const form=node('form');panel.append(form);const grid=node('div',undefined,'chat-policy-grid');form.append(grid);
    const enabled=field(grid,'enabled',input('checkbox',policy.enabled));
    const global=number(grid,'globalBudget',policy.daily_budget_usd,0.01,1000,0.01),perUser=number(grid,'userBudget',policy.user_daily_budget_usd,0.01,100,0.01),limit=number(grid,'daily',policy.user_daily_requests,1,100,1);
    const modelList=node('div',undefined,'chat-model-list');form.append(modelList);let controls=[];
    function modelRow(m){
      const box=node('fieldset',undefined,'chat-model'),legend=node('legend',m.label||t('model'));box.append(legend);const provider=node('select');for(const [id,label] of [['openai','OpenAI'],['anthropic','Anthropic · Claude'],['google','Google · Gemini']]){const o=node('option',label);o.value=id;provider.append(o)}provider.value=m.provider||'openai';field(box,'provider',provider);
      const id=field(box,'modelId',input('text',m.model_id)),label=field(box,'label',input('text',m.label));id.required=true;id.maxLength=100;label.required=true;label.maxLength=100;
      const priceIn=number(box,'inputCost',m.input_usd,0.000001,1000,0.000001),priceOut=number(box,'outputCost',m.output_usd,0.000001,1000,0.000001);
      const reference=field(box,'priceRef',input('text',m.price_reference));reference.required=true;reference.minLength=10;reference.maxLength=200;
      const allow=field(box,'enabled',input('checkbox',m.enabled)),verified=field(box,'verified',input('checkbox',m.verified));
      const row={box,provider,id,label,priceIn,priceOut,reference,allow,verified,limits:{max_input_chars:m.max_input_chars||24000,max_output_tokens:m.max_output_tokens||1200}};controls.push(row);
      const readiness=node('span','','accounts-help');function sync(){readiness.textContent=ready[provider.value]?t('enabled'):t('unavailable');allow.disabled=!ready[provider.value];if(allow.disabled)allow.checked=false}provider.addEventListener('change',sync);sync();box.append(readiness);const localize=()=>{sync();legend.textContent=label.value||t('model')};localizers.push(localize);
      box.append(button('removeModel',()=>{controls=controls.filter(c=>c!==row);localizers=localizers.filter(f=>f!==localize);box.remove()}));modelList.append(box);label.addEventListener('change',localize);
    }
    for(const m of policy.models)modelRow(m);const add=button('addModel',()=>{if(controls.length>=12)return;modelRow({})});form.append(add);
    const error=node('p','','chat-error');error.role='alert';form.append(error);const saved=node('p','','chat-status');saved.role='status';form.append(saved);const submit=translated('button','save','btn primary');submit.type='submit';form.append(submit);let errorKey=null,savedKey=null;localizers.push(()=>{error.textContent=errorKey?t(errorKey):'';saved.textContent=savedKey?t(savedKey):''});
    form.addEventListener('submit',async event=>{event.preventDefault();if(submit.disabled)return;submit.disabled=true;errorKey=savedKey=null;error.textContent='';saved.textContent='';
      const models=controls.map(c=>({provider:c.provider.value,model_id:c.id.value.trim(),label:c.label.value.trim(),input_usd:c.priceIn.value,output_usd:c.priceOut.value,price_reference:c.reference.value.trim(),enabled:c.allow.checked,verified:c.verified.checked,...c.limits}));
      try{await api('/admin/api/news-chat/policy',{method:'PUT',body:JSON.stringify({enabled:enabled.checked,daily_budget_usd:global.value,user_daily_budget_usd:perUser.value,user_daily_requests:Number(limit.value),models,projects:{}})});savedKey='saved';saved.textContent=t(savedKey)}catch(e){errorKey=e.message===t('expired')?'expired':e.message===t('denied')?'denied':'error';error.textContent=t(errorKey)}finally{submit.disabled=false}
    });
    const usage=node('details');usage.append(translated('summary','usage'));const body=node('div',undefined,'chat-usage');usage.append(body);panel.append(usage);let usageRows=[];const drawUsage=()=>{body.replaceChildren();for(const g of usageRows)body.append(node('p',[g.created_at,g.provider,g.model_id,t(g.status==='failed'?'error':g.status),'USD '+(g.actual_usd??g.reserved_usd)].join(' · ')))};localizers.push(drawUsage);usage.addEventListener('toggle',async()=>{if(!usage.open)return;try{const data=await api('/admin/api/news-chat/usage');usageRows=data.requests;drawUsage()}catch(e){body.textContent=e.message}});
  }
  function localize(){if(!panel?.isConnected)return;panel.querySelectorAll('[data-chat-admin-key]').forEach(n=>n.textContent=t(n.dataset.chatAdminKey));panel.querySelectorAll('[data-chat-admin-label]').forEach(n=>n.setAttribute('aria-label',t(n.dataset.chatAdminLabel)));localizers.forEach(f=>f());panel.dataset.locale=i18n.lang()}
  async function sync(){
    if(document.getElementById('app')?.classList.contains('hidden')){panel?.remove();panel=null;localizers=[];return}
    if(panel&&!panel.isConnected){panel=null;localizers=[]}
    if(!document.getElementById('view-account')?.classList.contains('active')||panel||busy)return;
    busy=true;try{const me=await api('/admin/api/me');if(!me.is_owner)return;const data=await api('/admin/api/news-chat/policy');policy=data.policy;ready=data.configured;if(!document.getElementById('app')?.classList.contains('hidden'))build(data)}catch(e){/* Account login remains usable when optional chat storage is unavailable. */}finally{busy=false}
  }
  const observer=new MutationObserver(sync);for(const id of ['app','view-account']){const n=document.getElementById(id);if(n)observer.observe(n,{attributes:true,attributeFilter:['class'],childList:id==='view-account',subtree:id==='view-account'})}
  // Translation updates labels in-place: never replace a form or fetch saved
  // policy over the owner's unsaved edits, selection, focus or pending save.
  new MutationObserver(localize).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});sync();
})();
