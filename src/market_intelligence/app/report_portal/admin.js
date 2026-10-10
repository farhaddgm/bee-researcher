(() => {
  const I=window.BeeReportI18n;let mounted=null,loading=false;
  const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  async function request(path,method='GET',body){const csrf=document.cookie.split('; ').find(v=>v.startsWith('research_bee_admin_csrf='))?.split('=').slice(1).join('=');const r=await fetch('/admin/api/report/'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(csrf||'')},body:body===undefined?undefined:JSON.stringify(body)});if(!r.ok)throw new Error('report_access');return r.json();}
  const choose=items=>{const n=el('select');for(const [v,label]of items){const o=el('option',label);o.value=v;n.append(o);}return n;};
  async function mount(){const host=document.getElementById('accountsPanel');if(!host||host===mounted||loading)return;loading=true;try{const data=await request('access');if(!data.enabled){mounted=host;return;}I.set(document.documentElement.lang);const t=I.t,card=el('section');card.className='report-access-card';card.id='reportAccessPanel';const heading=el('h3',t('reportAccess'));heading.append(el('small',' · '+t('owners')));card.append(heading,el('p',t('accessHelp')));const message=el('p');message.setAttribute('role','status');card.append(message);
    const action=(key,fn)=>{const b=el('button',t(key));b.type='button';b.className='btn primary';b.onclick=async()=>{b.disabled=true;try{await fn();message.textContent=t('configured');}catch{message.textContent=t('setupError');}finally{b.disabled=false;}};return b;};
    const field=(key,control,id)=>{const group=el('div');group.className='report-field';const label=el('label',t(key));control.id=id;label.htmlFor=id;group.append(label,control);return group;};
    const project=choose(data.projects.map(p=>[p.id,p.name]));
    const bindAction=action('bind',async()=>{await request('businesses','POST',{assistant_id:project.value});card.remove();mounted=null;await mount();});bindAction.disabled=!data.projects.length;
    card.append(field('project',project,'reportBindProject'),bindAction);
    if(data.businesses.length){
      const grid=el('div');grid.className='report-grid';
      const biz=choose(data.businesses.map(b=>[b.id,b.name])),account=choose(data.users.map(u=>[u.id,u.name])),role=choose([['reporter',t('reporterRole')],['manager',t('managerRole')]]),active=el('input');active.type='checkbox';active.checked=true;
      const projects=el('fieldset');projects.id='reportGrantProjects';projects.className='report-grant-projects';
      function update(){projects.replaceChildren(el('legend',t('project')));const b=data.businesses.find(b=>b.id===biz.value);for(const id of b.projects){const label=el('label'),control=el('input');control.type='checkbox';control.value=id;control.checked=true;label.append(control,el('span',data.projects.find(p=>p.id===id)?.name||id));projects.append(label);}}
      biz.onchange=update;update();
      for(const [key,control,id]of [['business',biz,'reportBusinessAccess'],['account',account,'reportAccountAccess'],['role',role,'reportRoleAccess'],['active',active,'reportGrantActive']])grid.append(field(key,control,id));grid.append(projects);
      card.append(grid,action('grant',async()=>{await request('grants','PUT',{business_id:biz.value,user_id:account.value,role:role.value,active:active.checked,assistant_ids:[...projects.querySelectorAll('input:checked')].map(c=>c.value)});card.remove();mounted=null;await mount();}));
      for(const g of data.grants){const row=el('button');row.type='button';row.className='btn secondary';row.textContent=(data.users.find(u=>u.id===g.user_id)?.name||g.user_id)+' · '+(data.businesses.find(b=>b.id===g.business_id)?.name||'')+' · '+t(g.role==='manager'?'managerRole':'reporterRole')+(g.active?' ✓':' —');row.onclick=()=>{biz.value=g.business_id;account.value=g.user_id;role.value=g.role;active.checked=g.active;update();for(const c of projects.querySelectorAll('input'))c.checked=g.assistant_ids.includes(c.value);};card.append(row);}
    }
    host.append(card);mounted=host;
  }catch{mounted=host;}finally{loading=false;}}
  const observer=new MutationObserver(()=>{if(mounted&&!document.contains(mounted))mounted=null;mount();});observer.observe(document.body,{childList:true,subtree:true});new MutationObserver(()=>{document.getElementById('reportAccessPanel')?.remove();mounted=null;mount();}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});mount();
})();
