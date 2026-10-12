/* Same server-enforced quotas in both owner portals; readers see only themselves. */
(() => {
  'use strict';
  const copy=window.BeeTokenI18n;if(!copy)return;
  const t=copy.t,$=id=>document.getElementById(id),admin=location.pathname.startsWith('/admin');
  const ownerURL=admin?'/admin/api/token-quotas':'/user/api/token-quotas/owner';
  const windows=['six_hours','daily','monthly','total'];
  let built=false,busy=false,epoch=0,reportSeq=0,ownerSeq=0,reportData=null,reportRows=[],older=null,catalog=null;
  let reportSection,reportProject,reportStatus,summaryBody,requestBody,olderButton,ownerSection,ownerProject,userSelect,projectEditor,userEditor;
  const editors=[];
  const node=(tag,key,cls)=>{const n=document.createElement(tag);if(key){n.dataset.tokenKey=key;n.textContent=t(key)}if(cls)n.className=cls;return n};
  const plain=(tag,text,cls)=>{const n=node(tag,null,cls);n.textContent=text;return n};
  const button=(key,action)=>{const n=node('button',key,'btn');n.type='button';n.addEventListener('click',action);return n};
  function label(parent,key,control){const l=node('label');l.append(node('span',key),control);control.dataset.tokenLabel=key;control.setAttribute('aria-label',t(key));parent.append(l);return control}
  async function api(path,options={}){
    const name=admin?'research_bee_admin_csrf':'research_bee_user_csrf';
    const csrf=document.cookie.split('; ').find(c=>c.startsWith(name+'='))?.split('=').slice(1).join('=');
    const r=await fetch(path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(options.method?{'X-CSRF-Token':decodeURIComponent(csrf||'')}:{}),...(options.headers||{})}});
    const data=await r.json().catch(()=>({}));if(!r.ok){const e=new Error(r.status===401?'expired':r.status===403?'denied':r.status===409?'conflict':'error');e.status=r.status;throw e}return data;
  }
  function status(n,key,error=false){n.dataset.tokenKey=key;n.textContent=key?t(key):'';n.classList.toggle('token-error',error)}
  function number(value){return value===null||value===undefined?t('unlimited'):new Intl.NumberFormat(copy.lang()).format(value)}
  function date(value){return value?new Intl.DateTimeFormat(copy.lang(),{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Tehran'}).format(new Date(value)):t('noReset')}
  function options(control,items){control.replaceChildren(...items.map(([value,text])=>{const o=plain('option',text);o.value=value;return o}))}
  function table(parent,keys){const wrap=node('div',null,'token-table-wrap');wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.dataset.tokenLabel=keys[0];wrap.setAttribute('aria-label',t(keys[0]));const table=node('table'),head=node('thead'),row=node('tr');keys.forEach(k=>{const th=node('th',k);th.scope='col';row.append(th)});head.append(row);const body=node('tbody');table.append(head,body);wrap.append(table);parent.append(wrap);return body}
  function drawReport(){
    summaryBody.replaceChildren();requestBody.replaceChildren();if(!reportData){olderButton.hidden=true;return}
    for(const w of reportData.windows){const row=node('tr');row.dataset.tokenWindow=w.window;for(const v of [t(w.window),number(w.input_tokens),number(w.output_tokens),number(w.reserved_tokens),number(w.charged_tokens),number(w.limit),number(w.remaining_tokens),date(w.reset_at)])row.append(plain('td',v,'token-number'));summaryBody.append(row)}
    for(const g of reportRows){const row=node('tr');for(const v of [date(g.created_at),g.model,g.provider,t(g.status),g.input_tokens===null?t('unknown'):number(g.input_tokens),g.output_tokens===null?t('unknown'):number(g.output_tokens),number(g.reserved_tokens)])row.append(plain('td',v,'token-number'));requestBody.append(row)}
    olderButton.hidden=!older;
    const info=$('tokenReportOrigin');info.textContent=t('source')+': '+t(reportData.limit_source)+' · '+t('updated')+': '+date(reportData.as_of);
  }
  async function loadReport(more=false){
    const aid=reportProject.value;if(!aid)return;const stamp=++reportSeq,scope=epoch;
    status(reportStatus,'loading');olderButton.disabled=true;
    if(!more){reportData=null;reportRows=[];older=null;drawReport()}
    try{const data=await api('/user/api/assistants/'+encodeURIComponent(aid)+'/token-report'+(more&&older?'?before='+encodeURIComponent(older):''));if(stamp!==reportSeq||scope!==epoch)return;reportData=data;reportRows=more?[...reportRows,...data.requests]:data.requests;older=data.older_before;drawReport();status(reportStatus,reportRows.length?'':'empty')}
    catch(e){if(stamp===reportSeq&&scope===epoch)status(reportStatus,e.message,true)}finally{if(stamp===reportSeq)olderButton.disabled=false}
  }
  function editor(parent,title,inherit=true){
    const box=node('fieldset',null,'token-editor');box.dataset.tokenEditor=title;box.append(node('legend',title));
    const form=node('form'),check=node('input');check.type='checkbox';
    const inheritLabel=label(form,'inherit',check);inheritLabel.className='token-inherit';inheritLabel.hidden=!inherit;
    const fields=node('div',null,'token-fields'),inputs={};
    for(const w of windows){const n=node('input');n.type='number';n.min='0';n.max='1000000000000';n.step='1';n.inputMode='numeric';n.dataset.tokenField=w;inputs[w]=n;label(fields,w,n)}
    form.append(fields,node('p','valueHelp','token-help'));const submit=node('button','save','btn primary');submit.type='submit';const msg=node('p',null,'token-status');msg.role='status';form.append(submit,msg);box.append(form);parent.append(box);
    const e={box,check,inputs,submit,msg,row:null,pending:false};
    e.dirty=()=>Boolean(e.row)&&(check.checked!==Boolean(e.row.inherit)||(!check.checked&&windows.some(w=>inputs[w].value!==(e.row.limits[w]===null?'':String(e.row.limits[w])))));
    const reload=button('reload',async()=>{if(!e.row||e.pending||e.dirty()&&!window.confirm(t('discard')))return;const identity={...e.row},stamp=epoch;e.pending=true;check.disabled=true;sync();syncOwnerControls();status(msg,'loading');try{const data=await api(ownerURL+(identity.assistant_id?'?assistant_id='+encodeURIComponent(identity.assistant_id):''));if(stamp!==epoch)return;const row=identity.user_id?data.users.find(u=>u.id===identity.user_id)?.policy:identity.assistant_id?data.project:data.default;if(row)e.apply(row)}catch(err){if(stamp===epoch)status(msg,err.message,true)}finally{e.pending=false;check.disabled=false;sync();syncOwnerControls()}});form.append(reload);editors.push(e);
    function sync(){for(const n of Object.values(inputs))n.disabled=check.checked||e.pending;submit.disabled=e.pending}
    const inherited=()=>title==='user'&&catalog?.project&&!catalog.project.inherit?catalog.project.limits:catalog?.default?.limits||{};
    const display=values=>{for(const w of windows)inputs[w].value=values[w]??''};
    check.addEventListener('change',()=>{if(check.checked)display(inherited());sync()});
    e.apply=row=>{e.row=row;check.checked=Boolean(row.inherit);display(row.inherit?inherited():row.limits);status(msg,'');sync()};
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(e.pending||!e.row)return;
      const limits={};for(const w of windows){limits[w]=inputs[w].value.trim()===''?null:Number(inputs[w].value);if(limits[w]!==null&&(!Number.isSafeInteger(limits[w])||limits[w]<0||limits[w]>1e12)){status(msg,'invalid',true);return}}
      const body={assistant_id:e.row.assistant_id,user_id:e.row.user_id,inherit:check.checked,limits,version:e.row.version};
      e.pending=true;check.disabled=true;sync();syncOwnerControls();status(msg,'saving');const stamp=epoch;
      try{const saved=await api(ownerURL,{method:'PUT',body:JSON.stringify(body)});if(stamp!==epoch)return;e.apply(saved);status(msg,'saved');if(catalog){if(title==='default')catalog.default=saved;else if(title==='project')catalog.project=saved;else{const user=catalog.users.find(u=>u.id===saved.user_id);if(user)user.policy=saved}}if(reportProject&&(reportProject.value===saved.assistant_id||saved.assistant_id===null))loadReport()}
      catch(err){if(stamp===epoch)status(msg,err.message,true)}finally{e.pending=false;check.disabled=false;sync();syncOwnerControls()}
    });return e;
  }
  function syncOwnerControls(){const pending=editors.some(e=>e.pending);if(ownerProject)ownerProject.disabled=pending;if(userSelect)userSelect.disabled=pending||!catalog?.project}
  async function loadOwnerProject(){
    if(projectEditor?.pending||userEditor?.pending)return;
    if((projectEditor?.dirty()||userEditor?.dirty())&&!window.confirm(t('discard'))){ownerProject.value=projectEditor.row?.assistant_id||ownerProject.value;return}
    const aid=ownerProject.value,stamp=++ownerSeq,scope=epoch;projectEditor.box.hidden=true;userEditor.box.hidden=true;userSelect.disabled=true;
    if(!aid)return;status($('tokenOwnerStatus'),'loading');
    try{const data=await api(ownerURL+'?assistant_id='+encodeURIComponent(aid));if(stamp!==ownerSeq||scope!==epoch)return;catalog=data;projectEditor.apply(data.project);projectEditor.box.hidden=false;options(userSelect,data.users.map(u=>[u.id,u.name+' · '+u.username]));userSelect.disabled=false;userEditor.row=null;chooseUser();status($('tokenOwnerStatus'),'')}
    catch(e){if(stamp===ownerSeq&&scope===epoch)status($('tokenOwnerStatus'),e.message,true)}
  }
  function chooseUser(){if(userEditor?.pending)return;if(userEditor?.dirty()&&!window.confirm(t('discard'))){userSelect.value=userEditor.row?.user_id||userSelect.value;return}const user=catalog?.users.find(u=>u.id===userSelect.value);userEditor.box.hidden=!user;if(user)userEditor.apply(user.policy)}
  function buildReport(parent,projects){
    reportSection=node('section',null,'token-section');reportSection.id='tokenReport';reportSection.setAttribute('aria-labelledby','tokenReportTitle');const h=node('h2','report');h.id='tokenReportTitle';reportSection.append(h,node('p','reportHelp','token-help'),node('p','windowsHelp','token-help'));
    const controls=node('div',null,'token-controls');reportProject=label(controls,'projectSelect',node('select'));reportProject.id='tokenReportProject';options(reportProject,projects.map(p=>[p.id,p.name]));reportProject.addEventListener('change',()=>loadReport());controls.append(button('refresh',()=>loadReport()));reportSection.append(controls);
    reportStatus=node('p',null,'token-status');reportStatus.id='tokenReportStatus';reportStatus.role='status';const origin=node('p',null,'token-help');origin.id='tokenReportOrigin';reportSection.append(reportStatus,origin);
    summaryBody=table(reportSection,['window','input','output','reserved','charged','limit','remaining','reset']);reportSection.append(node('h3','history'));requestBody=table(reportSection,['time','model','provider','status','input','output','reserved']);olderButton=button('older',()=>loadReport(true));olderButton.hidden=true;reportSection.append(olderButton);parent.append(reportSection);loadReport();
  }
  function buildOwner(parent,data){
    catalog=data;ownerSection=node('section',null,'token-section');ownerSection.id='tokenLimits';ownerSection.setAttribute('aria-labelledby','tokenLimitsTitle');const h=node('h2','limits');h.id='tokenLimitsTitle';ownerSection.append(h,node('p','ownerHelp','token-help'),node('p','windowsHelp','token-help'));
    editor(ownerSection,'default',false).apply(data.default);
    const controls=node('div',null,'token-controls');ownerProject=label(controls,'projectSelect',node('select'));ownerProject.id='tokenOwnerProject';options(ownerProject,data.projects.map(p=>[p.id,p.name]));ownerProject.addEventListener('change',loadOwnerProject);controls.append(button('reload',()=>loadOwnerProject()));ownerSection.append(controls);const status=node('p',null,'token-status');status.id='tokenOwnerStatus';status.role='status';ownerSection.append(status);
    projectEditor=editor(ownerSection,'project');projectEditor.box.hidden=true;
    const choose=node('div',null,'token-controls');userSelect=label(choose,'userSelect',node('select'));userSelect.id='tokenOwnerUser';userSelect.addEventListener('change',chooseUser);ownerSection.append(choose);userEditor=editor(ownerSection,'user');userEditor.box.hidden=true;
    ownerSection.append(node('p','limitEffect','token-help'));parent.append(ownerSection);loadOwnerProject();
  }
  function nav(key,section){if($(section==='report'?'tokenReportNav':'tokenLimitsNav'))return;const a=node('a',null,'sidebar-item token-subnav');const icon=plain('span','▤','sidebar-icon');icon.setAttribute('aria-hidden','true');a.append(icon,node('span',key));a.href='/user/settings?section='+section;a.id=section==='report'?'tokenReportNav':'tokenLimitsNav';a.setAttribute('aria-label',t(key));a.dataset.tokenLabel=key;$('sidebarSettingsButton')?.after(a)}
  function localize(){document.querySelectorAll('[data-token-key]').forEach(n=>{if(n.dataset.tokenKey)n.textContent=t(n.dataset.tokenKey)});document.querySelectorAll('[data-token-label]').forEach(n=>n.setAttribute('aria-label',t(n.dataset.tokenLabel)));for(const e of editors)for(const input of Object.values(e.inputs))input.placeholder=t('unlimited');if(reportData)drawReport()}
  async function boot(){
    if($('app')?.classList.contains('hidden')){epoch++;reportSeq++;ownerSeq++;built=false;busy=false;reportData=null;reportRows=[];catalog=null;editors.length=0;for(const id of ['tokenReport','tokenLimits','tokenReportNav','tokenLimitsNav','tokenBootError'])$(id)?.remove();return}
    const settings=!admin&&location.pathname.replace(/\/+$/,'').endsWith('/user/settings');
    if(built&&admin&&!$('tokenLimits')&&ownerSection){built=false;editors.length=0}if(built||busy||admin&&!$('view-account')?.classList.contains('active'))return;
    busy=true;const stamp=epoch;
    try{
      const me=await api(admin?'/admin/api/me':'/user/api/me');if(stamp!==epoch)return;
      const isOwner=me.is_owner===true;
      if(!admin){nav('report','report');if(isOwner)nav('limits','limits')}
      if(settings){const data=await api('/user/api/assistants');if(stamp!==epoch)return;buildReport($('settingsPanel'),data.assistants||[])}
      if(isOwner&&(admin||settings)){const data=await api(ownerURL);if(stamp!==epoch)return;buildOwner(admin?$('view-account'):$('settingsPanel'),data)}
      built=true;localize();const section=new URLSearchParams(location.search).get('section');if(settings&&section)requestAnimationFrame(()=>$(section==='report'?'tokenReport':'tokenLimits')?.scrollIntoView({block:'start'}));
    }catch(e){if(settings&&stamp===epoch){const n=node('p',null,'token-status token-error');n.id='tokenBootError';status(n,e.message,true);$('settingsPanel').append(n)}}finally{if(stamp===epoch)busy=false}
  }
  new MutationObserver(boot).observe($('app'),{attributes:true,attributeFilter:['class']});if(admin&&$('view-account'))new MutationObserver(boot).observe($('view-account'),{attributes:true,attributeFilter:['class'],childList:true});
  new MutationObserver(localize).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});boot();
})();
