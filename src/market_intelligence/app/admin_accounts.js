/* Unified account management: stable DOM, native accessible dialogs, no inline handlers. */
(() => {
  'use strict';
  const i18n=window.BeeAccountI18n;if(!i18n)return;
  const t=i18n.t;
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n};
  const button=(label,action,primary=false)=>{const n=node('button',label,'btn'+(primary?' primary':''));n.type='button';n.addEventListener('click',action);return n};
  const csrf=()=>{const p=document.cookie.split('; ').find(v=>v.startsWith('research_bee_admin_csrf='));return p?decodeURIComponent(p.slice(p.indexOf('=')+1)):''};
  async function api(path,options={}){
    const response=await fetch(path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(options.method&&options.method!=='GET'?{'X-CSRF-Token':csrf()}:{}),...(options.headers||{})}});
    const data=await response.json().catch(()=>({}));
    if(!response.ok){const error=new Error(t(data.detail==='current password is incorrect'?'currentPasswordWrong':response.status===409?'conflict':response.status===403?'denied':response.status===422?'validation':response.status===401?'expired':'requestFailed'));error.status=response.status;throw error}return data;
  }
  let me=null,panel=null,rows=[],page=1,total=0,query='',pending=false,requestGeneration=0;
  const notify=()=>window.toast?.(t('saved'));
  function roleText(role){return t(role)}
  function methodText(method){return t(method==='google'?'googleOnly':method==='both'?'both':'passwordOnly')}
  function field(form,key,input,full=false){const wrap=node('div',undefined,'accounts-field'+(full?' accounts-full':''));const label=node('label',t(key));input.id='account-'+key;label.htmlFor=input.id;wrap.append(label,input);form.append(wrap);return wrap}
  function select(values,value){const n=node('select');for(const [key,label] of values){const o=node('option',label);o.value=key;n.append(o)}n.value=value;return n}
  function input(type,value=''){const n=node('input');n.type=type;n.value=value;return n}
  function check(parent,key,checked){const label=node('label',undefined,'accounts-check');const control=input('checkbox');control.checked=checked;label.append(control,node('span',t(key)));parent.append(label);return control}
  function shell(title){const origin=document.activeElement;const dialog=node('dialog',undefined,'accounts-dialog');dialog.dir=['fa','ar'].includes(i18n.lang())?'rtl':'ltr';const heading=node('h3',title);heading.id='account-dialog-title';dialog.setAttribute('aria-labelledby',heading.id);dialog.append(heading);document.body.append(dialog);dialog.addEventListener('close',()=>{dialog.remove();if(origin?.isConnected)origin.focus()});dialog.addEventListener('keydown',event=>{if(event.key!=='Tab')return;const controls=[...dialog.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]')].filter(n=>n.getClientRects().length&&!n.closest('[hidden]'));const first=controls[0],last=controls.at(-1);if(!first)return;if(event.shiftKey&&(document.activeElement===first||document.activeElement===dialog)){event.preventDefault();last.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}});return dialog}
  async function editAccount(item=null){
    const own=item?.id===me.id,owner=Boolean(me.is_owner);
    const dialog=shell(t(item?'edit':'add'));
    const form=node('form',undefined,'accounts-form');dialog.append(form);
    const name=input('text',item?.display_name||'');name.required=true;name.maxLength=160;field(form,'name',name);
    const email=input('email',item?.email||'');email.autocomplete='email';email.dir='ltr';email.required=!item||(!item.email&&owner);email.disabled=Boolean(item?.email)||Boolean(item&&!owner);field(form,'address',email);
    const role=select(['viewer','analyst','editor','assistant_admin',...(owner?['admin']:[])].map(r=>[r,roleText(r)]),item?.stored_role||'viewer');role.disabled=Boolean(own);field(form,'role',role);
    const method=select([['google',t('googleOnly')],['both',t('both')],['password',t('passwordOnly')]],item?.login_method||(owner?'google':'password'));
    method.disabled=!owner||own;const methodWrap=field(form,'method',method);methodWrap.append(node('p',t('methodHint'),'accounts-help'));
    const password=input('password');password.autocomplete='new-password';password.minLength=8;password.maxLength=128;const passwordWrap=field(form,'password',password);passwordWrap.append(node('p',t('passwordHint'),'accounts-help'));
    let current=null;if(own){current=input('password');current.autocomplete='current-password';field(form,'currentPassword',current)}
    const status=select([['true',t('active')],['false',t('disabled')]],String(item?.active!==false));status.disabled=Boolean(own);field(form,'status',status);
    const projects=node('fieldset',undefined,'accounts-full');projects.append(node('legend',t('projects')));form.append(projects);
    let available=[];try{available=(await api('/admin/api/assistants')).assistants||[]}catch(err){projects.append(node('p',err.message,'accounts-help'))}
    const projectControls=[];for(const project of available.filter(p=>!p.deleted_at)){
      const label=node('label',undefined,'accounts-check'),control=input('checkbox');control.value=project.id;control.checked=Boolean(item?.assistant_ids?.includes(project.id));control.disabled=Boolean(own);label.append(control,node('span',project.name));projects.append(label);projectControls.push(control)
    }
    if(!projectControls.length)projects.append(node('p',t('empty'),'accounts-help'));
    const access=node('fieldset',undefined,'accounts-full');access.append(node('legend',t('portal')));form.append(access);
    const portal=check(access,'portal',Boolean(item?.user_portal_access));const feedback=check(access,'feedback',Boolean(item?.user_feedback_access));
    const portalAllowed=owner||me.stored_role==='admin';
    portal.disabled=own||!portalAllowed||item?.is_owner||role.value==='admin';feedback.disabled=own||!portalAllowed||!portal.checked;
    access.append(node('p',t('portalHint'),'accounts-help'));
    const error=node('p','','accounts-error');error.role='alert';form.append(error);
    const actions=node('div',undefined,'accounts-dialog-actions');actions.append(button(t('cancel'),()=>dialog.close()));const submit=node('button',t('save'),'btn primary');submit.type='submit';actions.append(submit);form.append(actions);
    function dependencies(){
      passwordWrap.hidden=method.value==='google';password.disabled=method.value==='google';password.required=method.value!=='google'&&(!item||!item.has_password);
      if(current)current.closest('.accounts-field').hidden=method.value==='google';
      if(role.value==='admin'){portal.checked=true;portal.disabled=true}else portal.disabled=own||!portalAllowed;
      feedback.disabled=own||!portalAllowed||!portal.checked;if(!portal.checked)feedback.checked=false;
    }
    method.addEventListener('change',dependencies);role.addEventListener('change',dependencies);portal.addEventListener('change',dependencies);dependencies();
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(submit.disabled)return;error.textContent='';submit.disabled=true;
      const payload={display_name:name.value.trim()};
      if(!item||!item.email)payload.email=email.value.trim();
      if(!own){payload.role=role.value;payload.active=status.value==='true';payload.assistant_ids=projectControls.filter(c=>c.checked).map(c=>c.value);if(portalAllowed){payload.user_portal_access=portal.checked;payload.user_feedback_access=feedback.checked}}
      if(!item)delete payload.active;
      if(owner&&!own||!item)payload.login_method=method.value;
      if(password.value&&method.value!=='google'){payload.password=password.value;if(own)payload.current_password=current.value}
      try{
        await api('/admin/api/accounts'+(item?'/'+encodeURIComponent(item.id):''),{method:item?'PATCH':'POST',body:JSON.stringify(payload)});
        dialog.close();notify();
        if(own&&payload.password){location.assign(me.login_method==='password'?'/admin/login-up':'/admin');return}
        await load();
      }catch(err){error.textContent=err.message;submit.disabled=false}
    });
    dialog.showModal();name.focus();
  }
  function confirmAction(item,google=false){
    const dialog=shell(t(google?'removeGoogle':'remove'));
    dialog.append(node('p',item.display_name),node('p',t(google?'revokeHint':'removeHint'),'accounts-help'));
    const error=node('p','','accounts-error');error.role='alert';dialog.append(error);
    const actions=node('div',undefined,'accounts-dialog-actions');actions.append(button(t('cancel'),()=>dialog.close()));
    const confirm=button(t(google?'removeGoogle':'remove'),async()=>{confirm.disabled=true;try{await api(google?'/admin/api/owner/google-access/'+encodeURIComponent(item.id):'/admin/api/accounts/'+encodeURIComponent(item.id),{method:'DELETE'});dialog.close();notify();load()}catch(err){error.textContent=err.message;confirm.disabled=false}});confirm.classList.add('danger');actions.append(confirm);dialog.append(actions);dialog.showModal();actions.firstChild.focus();
  }
  function renderRows(){
    const body=panel.querySelector('tbody');body.replaceChildren();
    for(const item of rows){
      const tr=node('tr'),identity=node('td'),copy=node('div',undefined,'accounts-identity');copy.append(node('strong',item.display_name),node('span',item.email||item.username,'accounts-email'));identity.append(copy);
      const role=node('td'),roleBadge=node('span',roleText(item.role),'accounts-status'+(item.is_owner?' is-owner':''));role.append(roleBadge);
      const status=node('td');status.append(node('span',t(item.active?'active':'disabled'),'accounts-status'+(item.active?' is-active':'')));
      const method=node('td',methodText(item.login_method)),last=node('td',item.last_login_at?new Intl.DateTimeFormat(i18n.lang(),{dateStyle:'short',timeStyle:'short'}).format(new Date(item.last_login_at)):'—');
      const cell=node('td'),actions=node('div',undefined,'accounts-actions');
      if(item.can_manage||item.id===me.id)actions.append(button(t('edit'),()=>editAccount(item)));
      if(item.can_manage&&me.is_owner&&item.login_method!=='password')actions.append(button(t('removeGoogle'),()=>confirmAction(item,true)));
      if(item.can_manage&&(me.is_owner||me.stored_role==='admin'))actions.append(button(t('remove'),()=>confirmAction(item)));
      cell.append(actions);tr.append(identity,role,method,status,last,cell);body.append(tr);
    }
    if(!rows.length){const tr=node('tr'),td=node('td',t('empty'));td.colSpan=6;tr.append(td);body.append(tr)}
    panel.querySelector('.accounts-page').textContent=String(page)+' / '+String(Math.max(1,Math.ceil(total/20)));
    panel.querySelector('[data-page="previous"]').disabled=page<=1;panel.querySelector('[data-page="next"]').disabled=page*20>=total;
  }
  async function load(){
    const generation=++requestGeneration;const error=panel.querySelector('.accounts-load-error');error.textContent='';
    panel.setAttribute('aria-busy','true');
    try{const data=await api('/admin/api/accounts?'+new URLSearchParams({q:query,page:String(page)}));if(generation!==requestGeneration)return;rows=data.accounts;total=data.total;renderRows()}catch(err){if(generation===requestGeneration)error.textContent=err.message}
    finally{if(generation===requestGeneration)panel.removeAttribute('aria-busy')}
  }
  function build(){
    const host=document.getElementById('accountSecurityPanel')||document.getElementById('view-account');if(!host)return;
    document.getElementById('userRows')?.closest('.card')?.classList.add('accounts-legacy');document.getElementById('newUserBtn')?.classList.add('accounts-legacy');
    document.getElementById('userRows')?.closest('.grid')?.classList.add('accounts-session-grid');
    panel=node('section',undefined,'card section-card');panel.id='accountsPanel';
    panel.dataset.locale=i18n.lang();
    const head=node('div',undefined,'accounts-head');head.append(node('h3',t('accounts')));const actions=node('div',undefined,'accounts-actions');
    const reload=button(t('refresh'),()=>load());reload.textContent='↻';reload.setAttribute('aria-label',t('refresh'));actions.append(reload);
    if(me.is_owner||['admin','assistant_admin'].includes(me.stored_role))actions.append(button(t('add'),()=>editAccount(),true));head.append(actions);panel.append(head,node('p',t('directory'),'accounts-description'));
    const profile=node('p',undefined,'accounts-description');profile.append(node('strong',t('ownAccount')+': '+me.display_name),node('span',' · '+(me.email||me.username)+' · '+methodText(me.login_method)));panel.append(profile);
    if(me.is_owner){const info=node('p',undefined,'accounts-description');info.id='googleAccountsInfo';info.append(node('span',t('ownersOnly'),'accounts-status is-owner'),node('span',' '+t(document.body.dataset.googleReady==='true'?'googleReady':'not_configured')));panel.append(info)}
    if(me.login_method==='google')panel.append(node('p',t('googlePasswordHint'),'accounts-help'));
    const tools=node('div',undefined,'accounts-tools'),search=input('search',query);search.className='accounts-search';search.placeholder=t('search');search.setAttribute('aria-label',t('search'));let timer;
    search.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>{query=search.value;page=1;load()},200)});tools.append(search);panel.append(tools);
    const error=node('p','','accounts-load-error accounts-help');error.role='alert';panel.append(error);
    const scroll=node('div',undefined,'accounts-scroll'),table=node('table'),thead=node('thead'),tr=node('tr');for(const key of ['name','role','method','status','lastLogin','edit']){const th=node('th',t(key));th.scope='col';tr.append(th)}thead.append(tr);table.append(thead,node('tbody'));scroll.append(table);panel.append(scroll);
    const pagination=node('nav',undefined,'accounts-pagination');for(const key of ['previous','next']){const b=button(t(key),()=>{page+=key==='next'?1:-1;load()});b.dataset.page=key;pagination.append(b);if(key==='previous')pagination.append(node('span','','accounts-page'))}panel.append(pagination);
    host.prepend(panel);load();
    // Legacy password dialog must not be offered for a Google-only account.
    for(const b of document.querySelectorAll('[id*="Password"],[id*="password"]'))if(b.tagName==='BUTTON'&&me.login_method==='google'&&!panel.contains(b))b.classList.add('accounts-legacy');
  }
  async function sync(){
    const app=document.getElementById('app'),view=document.getElementById('view-account');
    if(!app||app.classList.contains('hidden')){document.querySelector('.accounts-dialog')?.close();panel?.remove();panel=null;me=null;return}
    if(!view?.classList.contains('active')||pending)return;
    if(panel)return;pending=true;
    try{me=await api('/admin/api/me');build()}catch(_){}finally{pending=false}
  }
  const app=document.getElementById('app'),view=document.getElementById('view-account');const observer=new MutationObserver(sync);
  if(app)observer.observe(app,{attributes:true,attributeFilter:['class']});if(view)observer.observe(view,{attributes:true,attributeFilter:['class']});
  new MutationObserver(()=>{if(panel?.dataset.locale===i18n.lang())return;document.querySelector('.accounts-dialog')?.close();if(panel){panel.remove();panel=null;if(me)build()}}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
  sync();
})();
