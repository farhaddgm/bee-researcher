
/* Owner-only "Gmail sign-in" allowlist panel on the Security page. */
(function(){
  const fa=()=>(document.documentElement.lang||'fa').startsWith('fa');
  const t=(p,e)=>fa()?p:e;
  function csrf(){const part=document.cookie.split('; ').find(v=>v.startsWith('research_bee_admin_csrf='));return part?decodeURIComponent(part.split('=').slice(1).join('=')):''}
  async function api(path,options={}){
    const method=(options.method||'GET').toUpperCase();
    const headers={'Content-Type':'application/json'};if(method!=='GET')headers['X-CSRF-Token']=csrf();
    const r=await fetch(path,{credentials:'same-origin',...options,method,headers});
    const text=await r.text();let body={};try{body=text?JSON.parse(text):{}}catch(_){}
    if(!r.ok){const d=body.detail;throw Error(typeof d==='string'?d:t('درخواست ناموفق بود','Request failed'))}
    return body;
  }
  const say=(msg,bad)=>{if(typeof window.toast==='function')window.toast(msg,bad);else if(bad)alert(msg)};
  const el=(tag,attrs={},text)=>{const n=document.createElement(tag);for(const[k,v]of Object.entries(attrs)){if(k==='class')n.className=v;else n.setAttribute(k,v)}if(text!==undefined)n.textContent=text;return n};
  const methodLabel=m=>m==='google'?t('فقط جیمیل','Gmail only'):m==='both'?t('جیمیل و رمز عبور','Gmail + password'):t('رمز عبور','Password');
  let owner=null,building=false;
  async function render(panel){
    const body=panel.querySelector('tbody'),note=panel.querySelector('.google-access-note');
    body.textContent='';
    let data;try{data=await api('/admin/api/owner/google-access')}catch(err){note.textContent=err.message;return}
    note.textContent=data.google_login_configured?t('ورود با گوگل فعال است. مالک: ','Google sign-in is enabled. Owner: ')+data.owner_email:t('ورود با گوگل روی سرور پیکربندی نشده است (GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI). فهرست را می‌توانید از قبل آماده کنید.','Google sign-in is not configured on the server yet; you can prepare the list in advance.');
    for(const a of data.accounts){
      const tr=el('tr');
      tr.append(el('td',{},a.email),el('td',{},a.username),el('td',{},methodLabel(a.login_method)),el('td',{},a.is_owner?t('مالک','Owner'):a.role),el('td',{},a.active?t('فعال','Active'):t('غیرفعال','Disabled')),el('td',{},a.linked?t('متصل','Linked'):t('در انتظار اولین ورود','Awaiting first sign-in')));
      const actions=el('td',{class:'actions'});
      if(!a.is_owner){
        const toggle=el('button',{class:'btn small',type:'button'},a.active?t('غیرفعال‌سازی','Disable'):t('فعال‌سازی','Enable'));
        toggle.addEventListener('click',async()=>{try{await api('/admin/api/owner/google-access/'+encodeURIComponent(a.id),{method:'PATCH',body:JSON.stringify({active:!a.active})});render(panel)}catch(err){say(err.message,true)}});
        const method=el('button',{class:'btn small',type:'button'},a.login_method==='google'?t('اجازهٔ رمز عبور','Allow password'):t('فقط جیمیل','Gmail only'));
        method.addEventListener('click',async()=>{let body={login_method:a.login_method==='google'?'both':'google'};if(body.login_method==='both'&&!a.has_password){const pw=prompt(t('رمز عبور جدید (حداقل ۱۲ کاراکتر):','New password (min 12 characters):'));if(!pw)return;body.password=pw}try{await api('/admin/api/owner/google-access/'+encodeURIComponent(a.id),{method:'PATCH',body:JSON.stringify(body)});render(panel)}catch(err){say(err.message,true)}});
        const remove=el('button',{class:'btn small danger',type:'button'},t('حذف دسترسی','Remove'));
        remove.addEventListener('click',async()=>{if(!confirm(t('دسترسی جیمیل این حساب حذف شود؟','Remove Gmail access for this account?')))return;try{await api('/admin/api/owner/google-access/'+encodeURIComponent(a.id),{method:'DELETE'});render(panel)}catch(err){say(err.message,true)}});
        actions.append(toggle,method,remove);
      }
      tr.append(actions);body.append(tr);
    }
  }
  function build(){
    const view=document.getElementById('view-team');
    if(!view||document.getElementById('googleAccessPanel')||building)return;
    building=true;
    const panel=el('div',{id:'googleAccessPanel',class:'card section-card'});
    const head=el('div',{class:'section-title'});const titles=el('div');titles.append(el('h3',{},t('ورود با جیمیل','Gmail sign-in')),el('span',{},t('فقط حساب‌هایی که اینجا اضافه شوند می‌توانند با گوگل وارد شوند.','Only accounts listed here can sign in with Google.')));head.append(titles);
    const note=el('p',{class:'muted google-access-note'});
    const form=el('form',{class:'form-grid'});
    const field=(label,input)=>{const f=el('div',{class:'field'});f.append(el('label',{},label),input);return f};
    const email=el('input',{type:'email',required:'',placeholder:'name@gmail.com'});
    const role=el('select');for(const[v,l]of[['viewer',t('مشاهده‌گر','Viewer')],['editor',t('ویرایشگر','Editor')],['assistant_admin',t('مدیر پروژه','Project admin')],['admin',t('ادمین','Admin')]]){const o=el('option',{value:v},l);role.append(o)}
    const method=el('select');for(const[v,l]of[['google',t('فقط جیمیل','Gmail only')],['both',t('جیمیل و رمز عبور','Gmail + password')]]){method.append(el('option',{value:v},l))}
    const password=el('input',{type:'password',autocomplete:'new-password',placeholder:t('فقط برای «جیمیل و رمز عبور»','Only for Gmail + password')});
    const submit=el('button',{class:'btn small primary',type:'submit'},t('افزودن','Add'));
    form.append(field(t('جیمیل','Gmail'),email),field(t('نقش','Role'),role),field(t('روش ورود','Sign-in method'),method),field(t('رمز عبور','Password'),password),submit);
    form.addEventListener('submit',async e=>{e.preventDefault();const body={email:email.value.trim(),role:role.value,login_method:method.value};if(password.value)body.password=password.value;try{await api('/admin/api/owner/google-access',{method:'POST',body:JSON.stringify(body)});form.reset();say(t('دسترسی جیمیل اضافه شد','Gmail access added'));render(panel)}catch(err){say(err.message,true)}});
    const table=el('table');const thead=el('thead');const hr=el('tr');for(const h of[t('جیمیل','Gmail'),t('نام کاربری','Username'),t('روش ورود','Method'),t('نقش','Role'),t('وضعیت','Status'),t('اتصال گوگل','Google link'),''])hr.append(el('th',{},h));thead.append(hr);table.append(thead,el('tbody'));
    panel.append(head,note,form,table);view.appendChild(panel);
    building=false;render(panel);
  }
  async function check(){
    const app=document.getElementById('app');
    if(!app||app.classList.contains('hidden')){owner=null;document.getElementById('googleAccessPanel')?.remove();return}
    if(owner===null){try{owner=Boolean((await api('/admin/api/me')).is_owner)}catch(_){owner=false}}
    if(owner)build();
  }
  const app=document.getElementById('app');
  if(app)new MutationObserver(check).observe(app,{attributes:true,attributeFilter:['class']});
  setTimeout(check,1500);
})();
