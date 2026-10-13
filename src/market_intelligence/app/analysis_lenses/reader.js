/* Shared lens controls: selections are explicit, never paid on change. */
(() => {
  'use strict';
  const copy=window.BeeLensI18n;if(!copy)return;
  const t=copy.t;
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n};
  function label(key,control){const n=node('label');const text=node('span',t(key));text.dataset.lensKey=key;control.setAttribute('aria-label',t(key));control.dataset.lensLabel=key;n.append(text,control);return n}
  function button(key,action,primary=false){const n=node('button',t(key),'btn'+(primary?' primary':''));n.dataset.lensKey=key;n.type='button';n.addEventListener('click',action);return n}
  function info(key){const box=node('span',undefined,'lens-info'),b=node('button','i'),tip=node('span',t(key),'lens-tip');tip.dataset.lensKey=key;tip.role='tooltip';tip.id='lens-tip-'+copy.id();b.type='button';b.setAttribute('aria-describedby',tip.id);b.setAttribute('aria-label',t(key));const reveal=()=>box.classList.remove('is-dismissed');b.addEventListener('focus',reveal);box.addEventListener('mouseenter',reveal);b.addEventListener('click',()=>{const closing=box.classList.contains('is-open');box.classList.toggle('is-open',!closing);box.classList.toggle('is-dismissed',closing)});box.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();box.classList.remove('is-open');box.classList.add('is-dismissed')}});box.append(b,tip);return box}
  function errorKey(e){return e.status===401||e.status===410?'expired':e.status===429?'budget':['context_changed','lens_revision_changed','discovery_expired','lens_revoked'].includes(e.message)?'changed':'error'}
  window.BeeAnalysisLenses={mount({host,api,onChange,onAnalyze,onState,id='readerAnalysisLenses',businessControl=true}){
    let epoch=0,pid=null,aid=null,available=[],enabled=false,busy=false,fetching=false,snapshot=null,offset=null;
    let currentScope='focused',currentLens='',currentDays='30';const selected=new Map(),candidates=new Map();
    const panel=node('section',undefined,'analysis-lenses');panel.id=id;panel.hidden=true;
    const head=node('div',undefined,'lens-heading'),title=node('h3',t('title'));title.dataset.lensKey='title';head.append(title,info('help'));panel.append(head);
    const grid=node('div',undefined,'lens-controls'),scope=node('select'),lens=node('select'),days=node('select');
    for(const key of ['focused','contextual']){const o=node('option',t(key));o.value=key;o.dataset.lensKey=key;scope.append(o)}scope.title=t('helpScope');scope.dataset.lensTitle='helpScope';
    for(const n of [7,30,90,365]){const o=node('option',String(n));o.value=String(n);days.append(o)}days.value='30';
    grid.append(label('scope',scope),label('lens',lens));panel.append(grid);
    const business=node('input');business.type='checkbox';const businessLabel=node('label',undefined,'lens-toggle'),businessText=node('span',window.BeeNewsChatI18n?.t('includeBusiness')||t('private'));businessLabel.append(business,businessText);businessLabel.hidden=!businessControl;panel.append(businessLabel);
    business.addEventListener('change',()=>{if(!onChange()){business.checked=!business.checked;return}sync()});
    const summary=node('p','','lens-summary'),details=node('details'),dimensionTitle=node('summary',t('dimensions'));dimensionTitle.dataset.lensKey='dimensions';details.append(dimensionTitle);const dims=node('div');details.append(dims);panel.append(summary,details);
    const related=node('div'),actions=node('div',undefined,'lens-actions'),refresh=button('refresh',()=>{if(onChange())discover()}),more=button('more',()=>loadMore()),sources=node('div',undefined,'lens-sources'),count=node('p','','lens-summary');
    related.append(label('days',days),actions,count,sources);actions.append(refresh,more);related.hidden=true;panel.append(related);
    const message=node('p','','lens-status');message.role='alert';const run=button('analyze',()=>{if(valid())onAnalyze(t('analyzePrompt'));else message.textContent=t('none')},true),footer=node('div',undefined,'lens-actions'),reload=button('refresh',()=>{if(onChange())controller.open(pid,aid)});footer.append(reload,run);panel.append(message,footer);host.append(panel);
    const chosen=()=>available.find(v=>v.id===lens.value);
    function describe(){const item=chosen();summary.textContent=item?(item.labels?.[copy.lang()]?.summary||item.summary)+' · '+item.revision:'';dims.replaceChildren();for(const d of item?.dimensions||[]){const n=node('p',d.name+' — '+d.description);n.dir='auto';n.lang=item.source_language;dims.append(n)}if(item)details.title=t('referenceLanguage')+': '+item.source_language;for(const option of lens.options){const row=available.find(v=>v.id===option.value);if(row)option.textContent=row.labels?.[copy.lang()]?.name||row.name}}
    function valid(){return !fetching&&(!enabled||Boolean(chosen())&&(scope.value==='focused'||Boolean(snapshot)&&selected.size>0))}
    function sync(notify=true){related.hidden=scope.value!=='contextual';scope.disabled=busy||fetching;lens.disabled=busy||fetching;business.disabled=busy||fetching;days.disabled=busy||fetching;refresh.disabled=reload.disabled=busy||fetching;more.disabled=busy||fetching;more.hidden=offset===null;run.disabled=busy||!valid();run.hidden=!enabled;for(const input of sources.querySelectorAll('input'))input.disabled=busy||fetching;if(notify)onState?.()}
    function draw(){sources.replaceChildren();count.textContent=t('selection')+': '+(selected.size+1)+' / 5'+(snapshot?' · '+t('coverage')+': '+snapshot.coverage+(snapshot.limited?' (≤500)':''):'');
      for(const row of candidates.values()){const box=node('label',undefined,'lens-source'),check=node('input'),text=node('span',row.title);check.type='checkbox';check.checked=selected.has(row.id);check.setAttribute('aria-label',row.title);const date=node('small',[row.source_name,new Intl.DateTimeFormat(copy.lang(),{dateStyle:'medium'}).format(new Date(row.published_at))].filter(Boolean).join(' · '));const match=node('small',t(row.relationship)+': '+row.matches.map(t).join(', ')+' · '+t('independenceUnknown'));text.append(date,match);
        check.addEventListener('change',()=>{if(!onChange()){check.checked=selected.has(row.id);return}if(check.checked){if(selected.size>=4){check.checked=false;return}selected.set(row.id,row)}else selected.delete(row.id);draw();sync()});box.append(check,text);sources.append(box)}
      if(!candidates.size)sources.append(node('p',t('none'),'lens-summary'));sync();}
    async function discover(){if(!enabled||!pid||busy||fetching)return;const stamp=epoch;fetching=true;message.textContent=t('loading');sources.replaceChildren(node('div',undefined,'lens-skeleton'),node('div',undefined,'lens-skeleton'));sync();
      try{const result=await api('/user/api/publications/'+pid+'/analysis-discovery',{method:'POST',body:JSON.stringify({lookback_days:Number(days.value)})});if(stamp!==epoch)return;snapshot=result;offset=result.next_offset;selected.clear();candidates.clear();for(const row of result.candidates)candidates.set(row.id,row);message.textContent='';draw()}
      catch(e){if(stamp===epoch){snapshot=null;offset=null;selected.clear();candidates.clear();message.textContent=t(errorKey(e));sources.replaceChildren()}}
      finally{if(stamp===epoch){fetching=false;sync()}}}
    async function loadMore(){if(!snapshot||offset===null||busy||fetching)return;const stamp=epoch;fetching=true;sync();try{const data=await api('/user/api/analysis-discovery/'+snapshot.id+'?offset='+offset);if(stamp!==epoch)return;offset=data.next_offset;for(const row of data.candidates)candidates.set(row.id,row);draw()}catch(e){if(stamp===epoch)message.textContent=t(errorKey(e))}finally{if(stamp===epoch){fetching=false;sync()}}}
    scope.addEventListener('change',()=>{if(!onChange()){scope.value=currentScope;return}currentScope=scope.value;sync();if(scope.value==='contextual'&&!snapshot)discover()});
    lens.addEventListener('change',()=>{if(!onChange()){lens.value=currentLens;return}currentLens=lens.value;describe();sync()});
    days.addEventListener('change',()=>{if(!onChange()){days.value=currentDays;return}currentDays=days.value;discover()});
    const observer=new MutationObserver(()=>{for(const n of panel.querySelectorAll('[data-lens-key]'))n.textContent=t(n.dataset.lensKey);for(const n of panel.querySelectorAll('[data-lens-label]'))n.setAttribute('aria-label',t(n.dataset.lensLabel));for(const n of panel.querySelectorAll('[data-lens-title]'))n.title=t(n.dataset.lensTitle);businessText.textContent=window.BeeNewsChatI18n?.t('includeBusiness')||t('private');draw();describe()});observer.observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
    const controller={
      async open(news,project){this.close();pid=news;aid=project;const stamp=epoch;fetching=true;sync();
        try{const data=await api('/user/api/analysis-lenses?assistant_id='+encodeURIComponent(aid)+'&language='+copy.lang());if(stamp!==epoch)return;available=data.lenses;enabled=data.enabled&&available.length>0;lens.replaceChildren(...available.map(v=>{const o=node('option',v.name);o.value=v.id;return o}));const defaultItem=available.find(v=>v.key===data.default_key);if(enabled&&!defaultItem)throw new Error('analysis_default_unavailable');if(defaultItem)lens.value=defaultItem.id;currentLens=lens.value;panel.hidden=!enabled;grid.hidden=details.hidden=false;businessLabel.hidden=!businessControl;describe()}
        catch(e){if(stamp===epoch){enabled=false;panel.hidden=false;grid.hidden=details.hidden=businessLabel.hidden=true;message.textContent=t(errorKey(e))}}
        finally{if(stamp===epoch){fetching=false;sync()}}
      },
      close(){epoch++;pid=aid=null;available=[];enabled=false;fetching=false;snapshot=null;offset=null;selected.clear();candidates.clear();scope.value=currentScope='focused';days.value=currentDays='30';business.checked=false;lens.replaceChildren();sources.replaceChildren();panel.hidden=true;message.textContent='';},
      payload(){if(!enabled)return {};if(!valid())throw new Error('analysis_selection_invalid');const item=chosen();const value={analysis_profile:{scope:scope.value,lens_id:item.id,lens_revision:item.revision,lens_hash:item.hash,lookback_days:Number(days.value)}};if(businessControl)value.include_business=business.checked;if(scope.value==='contextual'){value.source_ids=[pid,...selected.keys()];value.analysis_profile.discovery_snapshot_id=snapshot.id}return value;},
      setBusy(value){busy=value;sync(false);},canSend:valid,active:()=>enabled,panel
    };return controller;
  }};
})();
