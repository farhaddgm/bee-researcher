/* Account defaults use the Reader's existing explicit Save/Reset controls. */
(() => {
  'use strict';
  const reader=window.BeeReader,copy=window.BeeNewsChatI18n;
  if(!reader||!copy)return;
  const t=copy.t,$=id=>document.getElementById(id);
  const lengthBase={short:{min:200,max:600},medium:{min:600,max:1600},long:{min:1600,max:4000}};
  const lengthModes=[['short','lengthShort'],['medium','lengthMedium'],['long','lengthLong'],['auto','lengthAuto']];
  const base={response_length:'auto',length_characters:lengthBase,provider:'openai',model_key:'',language:'en',voice_key:'',voice_consent:false,retain_voice:false,continuous_voice:false,voice_terms:''};
  const providers={openai:'OpenAI',anthropic:'Anthropic · Claude',google:'Google · Gemini'};
  const fields={},node=(tag,key,cls)=>{const n=document.createElement(tag);if(key){n.dataset.chatKey=key;n.textContent=t(key)}if(cls)n.className=cls;return n};
  const defaults=()=>({...base,...reader.chatDefaults()});
  let models=[],voices=[],catalogStarted=false,catalogSeq=0,editing=false;
  function value(){
    const result={};for(const [k,el] of Object.entries(fields))if(!k.startsWith('length_'))result[k]=el.type==='checkbox'?el.checked:el.value;
    result.length_characters={};for(const mode of ['short','medium','long'])result.length_characters[mode]={min:fields['length_'+mode+'_min'].valueAsNumber,max:fields['length_'+mode+'_max'].valueAsNumber};
    return result;
  }
  function validateLength(){
    const inputs=['short','medium','long'].flatMap(mode=>['min','max'].map(bound=>fields['length_'+mode+'_'+bound]));
    inputs.forEach(el=>el.setCustomValidity(''));
    for(const el of inputs)if(!el.validity.valid)return el;
    const ranges=value().length_characters;
    for(const mode of ['short','medium','long'])if(ranges[mode].min>ranges[mode].max){const el=fields['length_'+mode+'_max'];el.setCustomValidity(t('lengthInvalid'));return el}
    for(const bound of ['min','max'])if(ranges.short[bound]>ranges.medium[bound]||ranges.medium[bound]>ranges.long[bound]){const el=fields['length_medium_'+bound];el.setCustomValidity(t('lengthInvalid'));return el}
    return null;
  }
  function field(parent,key,name,tag='select',type){
    const label=node('label',null,'setting'),caption=node('span',key,'setting-label'),input=node(tag);
    input.id='news-chat-'+name.replaceAll('_','-');input.className='select';input.dataset.chatLabel=key;input.setAttribute('aria-label',t(key));
    if(type)input.type=type;if(type==='checkbox')label.classList.add('chat-setting-checkbox');
    label.append(caption,input);parent.append(label);fields[name]=input;
    input.addEventListener(tag==='input'&&type!=='checkbox'?'input':'change',()=>{
      if(name==='provider'){fields.model_key.value='';fillModels('')}
      if(name==='language')fillVoices(fields.voice_key.value);
      validateLength();editing=true;try{reader.updateChatDefaults(value())}finally{editing=false}
    });return input;
  }
  function options(select,items,selected,automatic=false){
    select.replaceChildren();
    if(automatic){const o=node('option','automatic');o.value='';select.append(o)}
    for(const [value,label] of items){const o=document.createElement('option');o.value=value;o.textContent=label;select.append(o)}
    if(selected&&![...select.options].some(o=>o.value===selected)){const o=node('option','unavailable');o.value=selected;select.append(o)}
    select.value=selected;
  }
  function fillModels(selected){options(fields.model_key,models.filter(m=>m.provider===fields.provider.value).map(m=>[m.key,m.label]),selected,true)}
  function fillVoices(selected){options(fields.voice_key,voices.filter(v=>v.languages.includes(fields.language.value)).map(v=>[v.key,v.label]),selected,true)}
  function applyVoiceDefaults(value){
    for(const name of ['voice_consent','retain_voice','continuous_voice'])fields[name].checked=Boolean(value[name]);
    fields.voice_terms.value=value.voice_terms||'';fillVoices(value.voice_key||'');
  }
  function sync(){
    const value=defaults();fields.provider.value=value.provider;fields.language.value=value.language;fillModels(value.model_key);applyVoiceDefaults(value);
    options(fields.response_length,lengthModes.map(([mode,key])=>[mode,t(key)]),value.response_length);
    for(const mode of ['short','medium','long'])for(const bound of ['min','max'])fields['length_'+mode+'_'+bound].value=value.length_characters?.[mode]?.[bound]??lengthBase[mode][bound];validateLength();
  }
  async function get(path){const response=await fetch(path,{credentials:'same-origin'});if(!response.ok)throw Error('catalog_unavailable');return response.json()}
  async function loadCatalog(){
    if(catalogStarted||$('app').classList.contains('hidden')||!location.pathname.replace(/\/+$/,'').endsWith('/user/settings'))return;
    catalogStarted=true;const stamp=++catalogSeq;catalogStatus.textContent=t('loading');
    try{
      const projects=await get('/user/api/assistants');
      const results=await Promise.allSettled((projects.assistants||[]).map(async a=>{
        const [chat,audio]=await Promise.allSettled([get('/user/api/chat/models?assistant_id='+encodeURIComponent(a.id)),get('/user/api/voice/capabilities?assistant_id='+encodeURIComponent(a.id))]);
        return {models:chat.status==='fulfilled'?chat.value.models||[]:[],voices:audio.status==='fulfilled'&&audio.value.enabled?audio.value.voices||[]:[]};
      }));
      if(stamp!==catalogSeq||$('app').classList.contains('hidden'))return;
      const values=results.filter(r=>r.status==='fulfilled').map(r=>r.value);
      models=[...new Map(values.flatMap(v=>v.models).map(m=>[m.key,m])).values()];
      const combined=new Map();for(const v of values.flatMap(v=>v.voices)){const prior=combined.get(v.key);combined.set(v.key,{...v,languages:[...new Set([...(prior?.languages||[]),...v.languages])]})}voices=[...combined.values()];
      catalogStatus.textContent=models.length?'':t('unavailable');sync();
    }catch(_){if(stamp===catalogSeq)catalogStatus.textContent=t('error')}
  }
  const section=node('section',null,'reader-chat-settings');section.id='readerChatSettings';section.setAttribute('aria-labelledby','readerChatSettingsTitle');
  const heading=node('h2','chatDefaults');heading.id='readerChatSettingsTitle';section.append(heading,node('p','defaultsHelp','chat-meta'));
  const grid=node('div',null,'settings-grid');
  const provider=field(grid,'provider','provider');options(provider,Object.entries(providers),'openai');
  field(grid,'model','model_key');const language=field(grid,'language','language');options(language,[['fa','فارسی'],['en','English'],['tr','Türkçe'],['ar','العربية'],['es','Español'],['it','Italiano'],['de','Deutsch'],['fr','Français']],'en');
  field(grid,'answerLength','response_length');
  const lengths=node('fieldset',null,'chat-length-settings');lengths.id='readerAnswerLengthSettings';lengths.append(node('legend','characterRanges'));const lengthHelp=node('p','lengthHelp','chat-meta');lengthHelp.id='readerLengthHelp';lengths.append(lengthHelp);
  for(const [mode,key] of lengthModes.filter(([mode])=>mode!=='auto')){const row=node('div',null,'chat-length-row');row.append(node('span',key,'chat-length-caption'));for(const bound of ['min','max']){const input=field(row,bound==='min'?'minCharacters':'maxCharacters','length_'+mode+'_'+bound,'input','number');input.min='1';input.max='20000';input.step='1';input.required=true;input.setAttribute('aria-describedby','readerLengthHelp');input.dataset.chatLengthMode=mode}lengths.append(row)}
  section.append(grid,lengths);const catalogStatus=node('p',null,'chat-status');catalogStatus.role='status';section.append(catalogStatus);
  const voiceSection=node('fieldset',null,'voice-settings');voiceSection.id='readerVoiceSettings';voiceSection.append(node('legend','voiceChoice'));
  const voiceGrid=node('div',null,'settings-grid');field(voiceGrid,'voiceChoice','voice_key').id='news-chat-voice';field(voiceGrid,'voiceConsent','voice_consent','input','checkbox');field(voiceGrid,'retainVoice','retain_voice','input','checkbox');field(voiceGrid,'continuousVoice','continuous_voice','input','checkbox');
  const terms=field(voiceGrid,'voiceTerms','voice_terms','input','text');terms.maxLength=3000;voiceSection.append(voiceGrid,node('p','voiceTermsCost','chat-meta'),node('p','voiceCost','chat-meta'));section.append(voiceSection);
  $('settingsPanel')?.querySelector('.settings-actions')?.before(section);
  window.BeeChatSettings={defaults,applyVoiceDefaults,fields};
  window.addEventListener('bee:reader-preferences',()=>{if(!editing)sync();loadCatalog()});
  $('saveSettingsButton')?.addEventListener('click',event=>{const invalid=validateLength();if(invalid){event.preventDefault();event.stopImmediatePropagation();$('settingsSaveNote').textContent=t('lengthInvalid');invalid.focus();invalid.reportValidity()}},true);
  new MutationObserver(()=>{
    if($('app').classList.contains('hidden')){catalogSeq++;catalogStarted=false;models=[];voices=[];sync()}else loadCatalog();
  }).observe($('app'),{attributes:true,attributeFilter:['class']});
  new MutationObserver(()=>{section.querySelectorAll('[data-chat-key]').forEach(n=>n.textContent=t(n.dataset.chatKey));section.querySelectorAll('[data-chat-label]').forEach(n=>n.setAttribute('aria-label',t(n.dataset.chatLabel)));if(location.pathname.replace(/\/+$/,'').endsWith('/user/settings'))sync()}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
  sync();loadCatalog();
})();
