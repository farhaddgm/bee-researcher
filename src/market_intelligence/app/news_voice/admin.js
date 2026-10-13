/* Owner-only, site-wide settings. Write-only secrets never enter policy JSON. */
(() => {
  'use strict';
  const copy=window.BeeNewsChatI18n;if(!copy)return;const t=copy.t;
  let panel=null,busy=false,ownerAllowed=null,credential=null,catalog={voices:[],models:[]},rows=[],controls={},localizers=[],sequence=0;
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n};
  function text(tag,key,cls){const n=node(tag,t(key),cls);n.dataset.voiceKey=key;return n}
  function button(key,action,primary=false){const b=text('button',key,'btn'+(primary?' primary':''));b.type='button';b.addEventListener('click',action);return b}
  function input(type,value){const n=node('input');n.type=type;if(type==='checkbox')n.checked=Boolean(value);else n.value=value??'';return n}
  function options(n,values,value){n.replaceChildren(...values.map(([id,label])=>{const o=node('option',label);o.value=id;return o}));n.value=value}
  function field(parent,key,control,help='voiceLimitsHelp'){
    const box=node('div',undefined,'voice-owner-field'),heading=node('div',undefined,'voice-field-heading'),label=text('label',key);
    control.id='voice-owner-'+key+'-'+sequence++;label.htmlFor=control.id;control.dataset.voiceLabel=key;
    const info=node('button','i','voice-owner-info');info.type='button';info.dataset.voiceHelp=help;info.dataset.voiceLabel=key;
    const tip=text('span',help,'voice-owner-tip');tip.id=control.id+'-help';tip.role='tooltip';info.setAttribute('aria-describedby',tip.id);
    heading.append(label,info,tip);box.append(heading,control);parent.append(box);return control;
  }
  function number(parent,key,value,min,max,step=1){const n=input('number',value);n.min=min;n.max=max;n.step=step;n.required=true;return field(parent,key,n,key.includes('Rate')||key.includes('Multiplier')?'voicePriceHelp':'voiceLimitsHelp')}
  function status(parent){const n=node('p','','voice-owner-status');n.role='status';n.setAttribute('aria-live','polite');parent.append(n);return n}
  function tell(n,key){n.dataset.voiceKey=key;n.textContent=t(key)}
  async function api(path,options={}){
    const cookie=document.cookie.split('; ').find(v=>v.startsWith('research_bee_admin_csrf='));
    const r=await fetch(path,{credentials:'same-origin',cache:'no-store',...options,headers:{'Content-Type':'application/json',...(options.method?{'X-CSRF-Token':cookie?decodeURIComponent(cookie.slice(cookie.indexOf('=')+1)):''}:{}),...(options.headers||{})}});
    const data=await r.json().catch(()=>({}));if(!r.ok){const e=new Error(data.detail||'error');e.status=r.status;throw e}return data;
  }
  const errorKey=e=>e.status===401?'expired':e.status===403?'denied':({revision_conflict:'voiceConflict',voice_key_invalid:'voiceInvalidKey',voice_permissions_missing:'voicePermissions',voice_rate_limited:'voiceThrottled',voice_credential_unavailable:'voiceStorageUnavailable',voice_unconfigured:'voiceMissingKey',voice_price_expired:'voiceExpiredPrice'}[e.message]||'voiceSetupError');
  function localize(){if(!panel?.isConnected)return;for(const n of panel.querySelectorAll('[data-voice-key]'))n.textContent=t(n.dataset.voiceKey);for(const n of panel.querySelectorAll('[data-voice-label]'))n.setAttribute('aria-label',t(n.dataset.voiceLabel));for(const f of localizers)f()}
  function voiceRow(value={}){
    if(rows.length>=12)return;
    const v={voice_id:'',label:'',model_id:'eleven_v3',transport:'http',languages:['fa','en'],verified:false,timing:false,max_chars:5000,usd_per_1000_chars:'',pronunciation_dictionaries:[],...value};
    const box=node('fieldset',undefined,'voice-owner-profile');box.append(text('legend','voiceProfile'));
    const id=field(box,'voiceId',input('text',v.voice_id),'voiceProfileHelp');id.required=true;id.minLength=8;id.maxLength=64;id.pattern='[A-Za-z0-9_-]+';id.dir='ltr';
    const names=node('datalist');names.id='voice-owner-list-'+sequence++;id.setAttribute('list',names.id);box.append(names);
    const label=field(box,'label',input('text',v.label),'voiceProfileHelp');label.required=true;label.maxLength=100;
    const model=field(box,'voiceModel',node('select'),'voiceProfileHelp');options(model,['eleven_v3','eleven_v3_conversational','eleven_v4','eleven_v4_turbo'].map(m=>[m,m]),v.model_id);
    const transport=field(box,'voiceTransport',node('select'),'voiceProfileHelp');options(transport,[['http','HTTP'],['ttd','TTD · WebSocket']],v.transport);
    const syncTransport=()=>{transport.value=model.value==='eleven_v3'?transport.value:'ttd';transport.disabled=model.value!=='eleven_v3'};model.addEventListener('change',syncTransport);syncTransport();
    const languages=node('div',undefined,'voice-owner-languages');languages.setAttribute('role','group');languages.dataset.voiceLabel='voiceLanguages';const langBox=node('div',undefined,'voice-owner-field');langBox.append(text('span','voiceLanguages'),languages);box.append(langBox);
    const langs={};for(const lang of ['fa','en','tr','ar','es','it','de','fr']){const l=node('label'),n=input('checkbox',v.languages.includes(lang));n.value=lang;l.append(n,node('span',new Intl.DisplayNames([lang],{type:'language'}).of(lang)));languages.append(l);langs[lang]=n}
    const rate=number(box,'voiceTtsRate',v.usd_per_1000_chars,0.000001,100,0.000001),chars=number(box,'voiceMaxChars',v.max_chars,100,10000);
    const verified=field(box,'voiceTested',input('checkbox',v.verified),'voiceVerificationHelp'),timing=field(box,'voiceTiming',input('checkbox',v.timing),'voiceProfileHelp');
    const dictionaries=node('textarea');dictionaries.rows=2;dictionaries.maxLength=1000;dictionaries.dir='ltr';dictionaries.value=v.pronunciation_dictionaries.map(d=>d.pronunciation_dictionary_id+','+d.version_id).join('\n');field(box,'voiceDictionaries',dictionaries,'voiceDictionaryHelp');
    const row={box,id,label,model,transport,langs,rate,chars,verified,timing,dictionaries};rows.push(row);const refresh=()=>{names.replaceChildren(...catalog.voices.map(v=>{const o=node('option');o.value=v.id;o.label=v.label;return o}))};localizers.push(refresh);refresh();
    id.addEventListener('change',()=>{const found=catalog.voices.find(v=>v.id===id.value);if(found&&!label.value)label.value=found.label});
    box.append(button('voiceRemoveProfile',()=>{rows=rows.filter(x=>x!==row);localizers=localizers.filter(f=>f!==refresh);box.remove()}));controls.profiles.append(box);
  }
  function build(data){
    credential=data.credential;rows=[];localizers=[];controls={};catalog={voices:[],models:[]};
    panel=node('section',undefined,'card section-card voice-owner-panel');panel.id='newsVoiceAdmin';panel.dataset.ownerOnly='true';
    const head=node('div',undefined,'section-title');head.append(text('h3','voiceAdmin'),text('span','owner','admin-ux-owner-badge'));panel.append(head,text('p','voiceGlobalHelp','muted'));
    if(!data.server_enabled)panel.append(text('p','voiceServerOff','notice'));
    const connection=node('div',undefined,'voice-owner-section');connection.append(text('h4','voiceConnection'));panel.append(connection);
    const key=input('password','');key.maxLength=500;key.minLength=16;key.autocomplete='new-password';key.spellcheck=false;key.dir='ltr';field(connection,'voiceApiKey',key,'voiceKeyHelp');key.id='elevenlabs-api-key';connection.querySelector('label').htmlFor=key.id;
    const keyState=status(connection),message=status(connection);const updateState=()=>{tell(keyState,!credential?.editable?'voiceStorageUnavailable':credential.configured?'voiceKeyConfigured':'voiceMissingKey');key.disabled=!credential?.editable};updateState();
    const actions=node('div',undefined,'voice-owner-actions');connection.append(actions);
    let keyBusy=false;const candidate=()=>key.value.trim();
    const probe=button('voiceCheckConnection',async()=>{if(keyBusy)return;keyBusy=true;setKeyBusy();tell(message,'voiceChecking');try{catalog=await api('/admin/api/news-voice/connection-check',{method:'POST',body:JSON.stringify(candidate()?{api_key:candidate()}:{})});tell(message,'voiceCheckSuccess');for(const f of localizers)f()}catch(e){tell(message,errorKey(e))}finally{keyBusy=false;setKeyBusy()}});
    const remove=button('voiceDeleteKey',async()=>{if(keyBusy||!window.confirm(t('voiceDeleteKeyConfirm')))return;await saveCredential('delete')});
    const saveKey=button('voiceSaveKey',async()=>{if(!key.reportValidity()||!candidate()){tell(message,'voiceInvalidKey');return}await saveCredential('set')},true);
    function setKeyBusy(){for(const b of [probe,remove,saveKey])b.disabled=keyBusy;saveKey.disabled=keyBusy||!credential?.editable;remove.disabled=keyBusy||!credential?.editable||!credential.configured;key.disabled=keyBusy||!credential?.editable}
    async function saveCredential(action){keyBusy=true;setKeyBusy();try{const r=await api('/admin/api/news-voice/credential',{method:'PUT',body:JSON.stringify({action,expected_revision:credential.revision,...(action==='set'?{api_key:candidate()}:{})})});credential=r.credential;key.value='';catalog={voices:[],models:[]};for(const f of localizers)f();next.disabled=true;if(controls.stt_verified)controls.stt_verified.checked=false;if(controls.zero_retention_verified)controls.zero_retention_verified.checked=false;for(const row of rows)row.verified.checked=false;updateState();tell(message,action==='delete'?'voiceKeyDeleted':'voiceKeyRetest')}catch(e){tell(message,errorKey(e));if(e.message==='revision_conflict'){const fresh=await api('/admin/api/news-voice/policy').catch(()=>null);if(fresh){credential=fresh.credential;updateState()}}}finally{keyBusy=false;setKeyBusy()}}
    const accountStatus=status(connection);actions.append(button('voiceCheckAccount',async()=>{try{const result=await api('/admin/api/news-voice/account-check',{method:'POST',body:'{}'});accountStatus.textContent=result.tier+' · '+t('voiceAccountRetentionHelp');delete accountStatus.dataset.voiceKey}catch(e){tell(accountStatus,errorKey(e))}}));
    actions.append(probe,remove,saveKey);setKeyBusy();connection.append(text('p','voiceCheckHelp','muted'));
    const searchGrid=node('div',undefined,'voice-owner-catalog'),search=field(searchGrid,'voiceSearch',input('search',''),'voiceProfileHelp'),searchStatus=status(searchGrid);search.maxLength=100;connection.append(searchGrid);
    let loading=false;const catalogActions=node('div',undefined,'voice-owner-actions');searchGrid.append(catalogActions);
    const next=button('voiceMoreVoices',()=>loadCatalog(catalog.next_page_token)),load=button('voiceLoadVoices',()=>loadCatalog(null));next.disabled=true;catalogActions.append(next,load);
    const pick=field(searchGrid,'voiceAccountVoice',node('select'),'voiceProfileHelp'),use=button('voiceUseVoice',()=>{const v=catalog.voices.find(v=>v.id===pick.value);if(v)voiceRow({voice_id:v.id,label:v.label})});searchGrid.append(use);
    localizers.push(()=>{const current=pick.value;options(pick,[['',t('voiceChooseVoice')],...catalog.voices.map(v=>[v.id,v.label])],catalog.voices.some(v=>v.id===current)?current:'');use.disabled=!pick.value});pick.addEventListener('change',()=>use.disabled=!pick.value);
    async function loadCatalog(token){if(loading)return;loading=true;load.disabled=next.disabled=true;try{const r=await api('/admin/api/news-voice/connection-check',{method:'POST',body:JSON.stringify({search:search.value.trim(),...(candidate()?{api_key:candidate()}:{}),...(token?{page_token:token}:{})})});catalog={...r,voices:token?[...catalog.voices,...r.voices].slice(-200):r.voices};tell(searchStatus,'voiceCheckSuccess');for(const f of localizers)f()}catch(e){tell(searchStatus,errorKey(e))}finally{loading=false;load.disabled=false;next.disabled=!catalog.has_more||!catalog.next_page_token}}
    const form=node('form');form.id='elevenlabs-policy-form';panel.append(form);const grid=node('div',undefined,'voice-owner-grid');form.append(grid);const p=data.policy;
    for(const [property,label,help] of [['enabled','voiceEnabled','voiceVerificationHelp'],['continuous_enabled','voiceContinuousEnabled','voiceContinuousHelp'],['stt_verified','voiceSttTested','voiceVerificationHelp'],['require_zero_retention','voiceZeroRetention','voicePrivacyHelp'],['zero_retention_verified','voiceRetentionVerified','voiceAccountRetentionHelp']])controls[property]=field(grid,label,input('checkbox',p[property]),help);
    controls.retention_reference=field(grid,'voiceRetentionReference',input('text',p.retention_reference),'voiceAccountRetentionHelp');controls.retention_reference.maxLength=240;
    const profiles=node('div');controls.profiles=profiles;form.append(text('h4','voiceProfiles'),text('p','voiceVerificationHelp','muted'),profiles,button('voiceAddProfile',()=>voiceRow()));for(const v of p.voices)voiceRow(v);
    form.append(text('h4','voicePricing'));form.append(button('voicePublishedPricing',()=>{const r=data.published_pricing;controls.stt_usd_per_minute.value=r.stt_usd_per_minute;controls.keyterms_multiplier.value=r.keyterms_multiplier;controls.price_reference.value=r.reference;controls.price_expires_at.value=new Date(new Date(r.expires_at).getTime()-new Date(r.expires_at).getTimezoneOffset()*60000).toISOString().slice(0,16);for(const row of rows)row.rate.value=r.tts_usd_per_1000_chars[row.model.value]}));const prices=node('div',undefined,'voice-owner-grid');form.append(prices);
    controls.stt_usd_per_minute=number(prices,'voiceSttRate',p.stt_usd_per_minute,0.000001,10,0.000001);controls.keyterms_multiplier=number(prices,'voiceTermsMultiplier',p.keyterms_multiplier,1,5,0.0000000001);
    controls.price_reference=field(prices,'priceRef',input('text',p.price_reference),'voicePriceHelp');controls.price_reference.maxLength=240;
    const expires=input('datetime-local',p.price_expires_at?new Date(new Date(p.price_expires_at).getTime()-new Date(p.price_expires_at).getTimezoneOffset()*60000).toISOString().slice(0,16):'');controls.price_expires_at=field(prices,'voicePriceExpiry',expires,'voicePriceHelp');
    controls.daily_budget_usd=number(prices,'budget',p.daily_budget_usd,0.000001,1000,0.000001);controls.user_daily_budget_usd=number(prices,'userBudget',p.user_daily_budget_usd,0.000001,100,0.000001);
    form.append(text('h4','voiceLimits'));const limits=node('div',undefined,'voice-owner-grid');form.append(limits);
    for(const [property,key,min,max] of [['max_input_seconds','voiceInputSeconds',10,120],['max_session_seconds','voiceSessionSeconds',30,600],['daily_stt_seconds','voiceDailySeconds',10,7200]])controls[property]=number(limits,key,p[property],min,max);
    const advanced=node('details',undefined,'voice-owner-advanced');advanced.append(text('summary','voiceStorage'));const advancedGrid=node('div',undefined,'voice-owner-grid');advanced.append(advancedGrid);form.append(advanced);
    controls.storage_bytes=number(advancedGrid,'voiceStorageMb',p.storage_bytes/1000000,1,2000);controls.max_audio_bytes=number(advancedGrid,'voiceAudioMb',p.max_audio_bytes/1000000,0.032,25,0.001);controls.staging_seconds=number(advancedGrid,'voiceStagingSeconds',p.staging_seconds,120,900);
    const retention=input('number',p.retention_days??'');retention.min=1;retention.max=3650;retention.placeholder=t('voiceNoExpiry');retention.dataset.voicePlaceholder='voiceNoExpiry';controls.retention_days=field(advancedGrid,'voiceRetentionDays',retention,'voicePrivacyHelp');
    const formStatus=status(form),formActions=node('div',undefined,'voice-owner-actions'),save=text('button','save','btn primary');save.type='submit';formActions.append(save);form.append(formActions);
    form.addEventListener('submit',async event=>{event.preventDefault();if(save.disabled)return;save.disabled=true;tell(formStatus,'voiceChecking');try{
      const result={};for(const [property,c] of Object.entries(controls)){if(property==='profiles')continue;if(c.type==='checkbox')result[property]=c.checked;else if(property==='price_expires_at')result[property]=c.value?new Date(c.value).toISOString():null;else if(property==='retention_days')result[property]=c.value?Number(c.value):null;else if(['price_reference','retention_reference'].includes(property))result[property]=c.value.trim();else if(property==='storage_bytes'||property==='max_audio_bytes')result[property]=Math.round(Number(c.value)*1000000);else result[property]=Number(c.value)}
      result.voices=rows.map(r=>({voice_id:r.id.value.trim(),label:r.label.value.trim(),model_id:r.model.value,transport:r.transport.value,languages:Object.entries(r.langs).filter(([,n])=>n.checked).map(([lang])=>lang),verified:r.verified.checked,timing:r.timing.checked,max_chars:Number(r.chars.value),usd_per_1000_chars:r.rate.value,pronunciation_dictionaries:r.dictionaries.value.trim()?r.dictionaries.value.trim().split('\n').map(line=>{const parts=line.split(',').map(v=>v.trim());if(parts.length!==2)throw Error('invalid_dictionary');return {pronunciation_dictionary_id:parts[0],version_id:parts[1]}}):[]}));
      await api('/admin/api/news-voice/policy',{method:'PUT',headers:{'X-Voice-Credential-Revision':credential.revision},body:JSON.stringify(result)});tell(formStatus,'saved');
    }catch(e){tell(formStatus,errorKey(e))}finally{save.disabled=false}});
    document.getElementById('view-settings').append(panel);localize();
  }
  async function sync(){
    if(document.getElementById('app')?.classList.contains('hidden')){if(panel){const key=panel.querySelector('[type=password]');if(key)key.value='';panel.remove()}panel=null;ownerAllowed=null;localizers=[];return}
    if(panel&&!panel.isConnected){panel=null;localizers=[]}
    if(!document.getElementById('view-settings')?.classList.contains('active')){const key=panel?.querySelector('[type=password]');if(key)key.value='';return}
    if(panel||busy||ownerAllowed===false)return;
    busy=true;try{if(ownerAllowed===null){const me=await api('/admin/api/me');ownerAllowed=Boolean(me.is_owner)}if(!ownerAllowed)return;const data=await api('/admin/api/news-voice/policy');if(!document.getElementById('app')?.classList.contains('hidden')&&document.getElementById('view-settings')?.classList.contains('active'))build(data)}catch(_){/* Optional voice settings do not break other settings. */}finally{busy=false}
  }
  const observer=new MutationObserver(sync);observer.observe(document.getElementById('app')||document.body,{attributes:true,attributeFilter:['class'],childList:true,subtree:true});
  new MutationObserver(()=>{localize();if(panel)for(const n of panel.querySelectorAll('[data-voice-placeholder]'))n.placeholder=t(n.dataset.voicePlaceholder)}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
  window.addEventListener('pagehide',()=>{const key=panel?.querySelector('[type=password]');if(key)key.value=''});sync();
})();
