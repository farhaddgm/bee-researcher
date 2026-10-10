/* Owner-only Settings report; identity snapshots are rendered as plain text. */
(() => {
  'use strict';
  const i18n=window.BeeAccountI18n;if(!i18n)return;
  const t=i18n.t;
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n};
  const button=(key,action)=>{const n=node('button',t(key),'btn');n.type='button';n.addEventListener('click',action);return n};
  let panel=null,me=null,checking=false,generation=0,page=1,pages=1,total=0,rows=[];
  const active=()=>!document.getElementById('app')?.classList.contains('hidden');
  async function api(path){
    const response=await fetch(path,{credentials:'same-origin'});
    if(!response.ok){const error=new Error(t(response.status===401?'expired':response.status===403?'denied':'requestFailed'));error.status=response.status;throw error}
    return response.json();
  }
  function render(){
    if(!panel)return;
    const body=panel.querySelector('tbody');body.replaceChildren();
    const dateFormat=new Intl.DateTimeFormat(i18n.lang(),{dateStyle:'short',timeStyle:'medium'});
    for(const item of rows){
      const tr=node('tr'),email=node('td',item.email||item.username||'—','login-history-email');email.dir='ltr';
      const date=node('td');const time=node('time',dateFormat.format(new Date(item.created_at)));time.dateTime=item.created_at;date.append(time);
      const status=node('td');status.append(node('span',t(item.outcome==='success'?'loginSuccess':'loginFailure'),'accounts-status '+(item.outcome==='success'?'is-active':'is-failed')));
      tr.append(email,date,status,node('td',t(item.method==='google'?'googleMethod':'passwordMethod')),
        node('td',item.portal==='report'?'Report':item.portal==='user'?'User':item.portal==='admin'?'Admin':'—'),node('td',item.reason?t(item.reason):'—'));body.append(tr);
    }
    if(!rows.length){const tr=node('tr'),td=node('td',t('loginEmpty'));td.colSpan=6;tr.append(td);body.append(tr)}
    const numbers=new Intl.NumberFormat(i18n.lang());
    panel.querySelector('.login-history-page').textContent=numbers.format(page)+' / '+numbers.format(pages)+' · '+numbers.format(total);
    panel.querySelector('[data-page="previous"]').disabled=page<=1;
    panel.querySelector('[data-page="next"]').disabled=page>=pages;
  }
  async function load(target=page){
    const root=panel,version=++generation;if(!root)return;
    const error=root.querySelector('[role="alert"]');error.textContent='';root.setAttribute('aria-busy','true');
    for(const b of root.querySelectorAll('button'))b.disabled=true;
    try{
      const data=await api('/admin/api/owner/login-history?'+new URLSearchParams({page:String(target)}));
      if(version!==generation||panel!==root)return;
      rows=data.attempts;page=data.page;pages=data.pages;total=data.total;
    }catch(err){
      if(version!==generation||panel!==root)return;
      if(err.status===401||err.status===403){root.remove();panel=null;me=null;return}
      error.textContent=err.message;
    }finally{
      if(version===generation&&panel===root){root.removeAttribute('aria-busy');root.querySelector('[data-refresh]').disabled=false;render()}
    }
  }
  function build(){
    const host=document.getElementById('accountSecurityPanel')||document.getElementById('view-account');if(!host)return;
    panel=node('section',undefined,'card section-card');panel.id='loginHistoryPanel';panel.dataset.locale=i18n.lang();
    const head=node('div',undefined,'login-history-head'),title=node('h3',t('loginHistory'));title.id='login-history-title';panel.setAttribute('aria-labelledby',title.id);
    const refresh=button('refresh',()=>load(1));refresh.dataset.refresh='true';head.append(title,refresh);panel.append(head,node('p',t('loginHistoryHint'),'accounts-help'));
    const error=node('p','','accounts-help');error.role='alert';panel.append(error);
    const scroll=node('div',undefined,'login-history-scroll'),table=node('table'),thead=node('thead'),tr=node('tr');
    for(const key of ['address','loginTime','loginOutcome','method','loginPortal','loginReason']){const th=node('th',t(key));th.scope='col';tr.append(th)}
    thead.append(tr);table.append(thead,node('tbody'));scroll.append(table);panel.append(scroll);
    const pagination=node('nav',undefined,'login-history-pagination');pagination.setAttribute('aria-label',t('loginHistory'));
    for(const key of ['previous','next']){const b=button(key,()=>load(page+(key==='next'?1:-1)));b.dataset.page=key;pagination.append(b);if(key==='previous'){const count=node('span','','login-history-page');count.setAttribute('aria-live','polite');pagination.append(count)}}
    panel.append(pagination);host.append(panel);render();load();
  }
  async function sync(){
    if(!active()){generation++;panel?.remove();panel=null;me=null;rows=[];page=1;pages=1;total=0;return}
    if(!document.getElementById('view-account')?.classList.contains('active')||panel||checking)return;
    checking=true;const version=generation;
    try{const user=await api('/admin/api/me');if(version!==generation||!active())return;me=user;if(me.is_owner)build()}catch(_){}finally{checking=false}
  }
  const observer=new MutationObserver(sync);
  for(const id of ['app','view-account']){const n=document.getElementById(id);if(n)observer.observe(n,{attributes:true,attributeFilter:['class']})}
  new MutationObserver(()=>{if(!panel||panel.dataset.locale===i18n.lang())return;generation++;panel.remove();panel=null;if(me?.is_owner&&active())build()}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
  sync();
})();
