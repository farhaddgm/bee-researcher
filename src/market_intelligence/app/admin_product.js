/* Read-only diagnostics: no polling, paid analysis or publication on page load. */
(() => {
  if (window.__beeProductDiagnostics) return;
  window.__beeProductDiagnostics = true;
  const $ = id => document.getElementById(id);
  const s = () => window.__researchBeeState;
  const L = key => typeof translatedCopy === 'function' ? translatedCopy(key) : key;
  const E = value => window.esc(String(value ?? ''));
  const N = value => new Intl.NumberFormat(s()?.language || 'en').format(Number(value || 0));
  const actor = () => `${s()?.currentUser?.id || ''}:${s()?.assistantId || ''}`;
  const owner = () => s()?.currentUser?.is_owner === true;
  const labels = {selected:'از آستانه عبور کرده',borderline:'نیازمند بررسی انسانی',rejected:'ردشده',pending:'منتظر امتیاز AI'};
  const reasons = {
    provider_quota_exhausted:'اعتبار API تمام شده؛ مالک باید حساب API را شارژ کند. خبرها محفوظ‌اند و بدون تحلیل معتبر منتشر نمی‌شوند.',
    provider_authentication_failed:'دسترسی API تأیید نشد؛ مالک باید کلید و مجوز API را در سرور بررسی کند.',
    provider_model_unavailable:'مدل انتخاب‌شده در دسترس نیست؛ مالک باید انتخاب مدل و دسترسی حساب API را بررسی کند.',
    provider_request_failed:'آخرین درخواست AI موفق نبود؛ جزئیات امن در عملیات ثبت شده است.',
    provider_not_configured:'کلید API یا مجوز تحلیل خارجی تنظیم نشده است.',
    no_enabled_sources:'برای این پروژه یک رسانهٔ فعال اضافه کنید.',
    no_enabled_topics:'برای این پروژه یک موضوع فعال و آستانهٔ ارتباط مشخص کنید.',
    workspace_inactive:'پروژه فعال نیست؛ خزش و تحلیل خودکار متوقف است.',
    relevance_budget_reached:'بودجهٔ روزانهٔ امتیازدهی مصرف شده؛ خبرها برای نوبت بعد محفوظ می‌مانند.'
  };
  let health = null, healthActor = '', healthSerial = 0, triageSerial = 0;
  let page = 0, filter = '', query = '', rows = [], result = null, mountedActor = '', busy = false;
  const view = () => document.querySelector('.view.active')?.id;
  function healthPanel() {
    const root = $(view());
    if (!root || !['view-overview','view-operations'].includes(root.id)) return null;
    let panel = root.querySelector('[data-product-health]');
    if (!panel) { panel=document.createElement('section');panel.className='product-health';panel.dataset.productHealth='';panel.setAttribute('aria-live','polite');root.querySelector('.page-head')?.after(panel); }
    return panel;
  }
  function paintHealth() {
    const node=healthPanel();if(!node)return;
    if(!health||healthActor!==actor()){node.textContent=L('در حال بررسی وضعیت تحلیل…');return;}
    const states={not_configured:'تنظیم نشده',not_checked:'هنوز آزموده نشده',blocked:'متوقف',error:'نیازمند بررسی',processing:'در حال تحلیل',last_attempt_succeeded:'آخرین درخواست موفق بود'};
    const notices=(health.blockers||[]).map(code=>`<p>${E(L(reasons[code]||'نیازمند بررسی'))}</p>`).join('');
    node.classList.toggle('needs-attention',Boolean(notices));
    node.innerHTML=`<h3>${E(L('وضعیت واقعی تحلیل خبر'))}</h3>${notices}<dl><div><dt>${E(L('وضعیت AI'))}</dt><dd>${E(L(states[health.provider?.state]||'هنوز آزموده نشده'))}</dd></div><div><dt>${E(L('منتظر امتیاز AI'))}</dt><dd>${N(health.pending_ai_articles)}</dd></div><div><dt>${E(L('مدل'))}</dt><dd data-user-content="true" dir="ltr">${E(health.model)}</dd></div><div><dt>${E(L('آخرین مشاهده'))}</dt><dd>${health.provider?.observed_at?E(new Date(health.provider.observed_at).toLocaleString(s().language)): '—'}</dd></div></dl>${owner()&&health.budgets?`<dl class="product-budgets">${Object.entries(health.budgets).map(([kind,b])=>`<div><dt>${E(L(kind==='relevance_model'?'بودجهٔ روزانهٔ امتیازدهی':'بودجهٔ روزانهٔ گزارش‌نویسی'))}</dt><dd>${N(b.used_requests)} / ${N(b.request_cap)}</dd></div>`).join('')}<div><dt>${E(L('منطقهٔ زمانی'))}</dt><dd data-user-content="true">${E(health.timezone)}</dd></div></dl>`:''}`;
  }
  async function loadHealth() {
    if(!s()?.currentUser||!s()?.assistantId||!healthPanel())return;
    const current=actor(),seq=++healthSerial;paintHealth();
    try {const data=await window.req('/operations/status',{coalesceGet:false});if(seq!==healthSerial||current!==actor())return;health=data;healthActor=current;paintHealth();}
    catch(error){if(seq===healthSerial&&current===actor()){const panel=healthPanel();if(panel)panel.textContent=L('وضعیت تحلیل دریافت نشد؛ بازخوانی کنید.');}}
  }
  function mountTriage() {
    const root=$('view-content');if(!root)return null;
    let node=$('productTriage');
    if(!node){node=document.createElement('details');node.id='productTriage';node.className='product-triage';root.querySelector('.page-head')?.after(node);node.addEventListener('toggle',()=>{if(node.open&&s()?.currentUser)loadTriage();});}
    if(!node.querySelector('summary'))node.innerHTML='<summary></summary><div class="product-triage-body"></div>';
    if(mountedActor!==actor()){mountedActor=actor();page=0;filter='';query='';rows=[];result=null;triageSerial++;}
    node.querySelector('summary').textContent=L('همهٔ خبرهای جمع‌آوری‌شده و تصمیم AI');
    return node;
  }
  function paintTriage() {
    const node=mountTriage();if(!node)return;
    const body=node.querySelector('.product-triage-body');
    body.innerHTML=`<p>${E(L('این فهرست مستقل از پیش‌نمایش انتشار است. تا ۵۰۰ خبر اخیرِ منطبق با جست‌وجو بررسی می‌شود؛ دیدن این بخش هزینهٔ AI ندارد.'))}</p><div class="product-triage-tools"><label>${E(L('جست‌وجوی عنوان یا رسانه'))}<input id="triageSearch" type="search" maxlength="200" value="${E(query)}"></label><label>${E(L('وضعیت تصمیم'))}<select id="triageFilter"><option value="">${E(L('همهٔ وضعیت‌ها'))}</option>${Object.entries(labels).map(([key,title])=>`<option value="${key}" ${filter===key?'selected':''}>${E(L(title))}</option>`).join('')}</select></label><button type="button" class="btn" id="triageSearchBtn">${E(L('جست‌وجو'))}</button><button type="button" class="btn" id="triageRefreshBtn">${E(L('بازخوانی'))}</button></div><div class="product-triage-counts">${Object.entries(result?.counts||{}).map(([key,count])=>`<span>${E(L(labels[key]))}: ${N(count)}</span>`).join('')}</div><div id="triageResults" aria-live="polite" aria-busy="${busy}">${busy?`<div class="empty">${E(L('در حال دریافت خبرها…'))}</div>`:rows.map(row=>`<article class="product-triage-row"><div><h4 data-user-content="true" dir="auto">${E(row.title)}</h4><small data-user-content="true" dir="auto">${E(row.source_name)}</small><br><button type="button" class="btn small" data-triage-detail="${E(row.id)}">${E(L('جزئیات تصمیم'))}</button></div><span class="product-triage-state ${E(row.relevance_state)}">${E(L(labels[row.relevance_state]))}${row.relevance_state!=='pending'&&row.relevance_score!=null?' · '+N(row.relevance_score):''}</span></article>`).join('')||`<div class="empty">${E(L('خبری با این جست‌وجو و وضعیت پیدا نشد.'))}</div>`}</div><div class="product-triage-footer"><span>${N(result?.total||0)} ${E(L('خبر در این فهرست'))}${result?.window_capped?' · '+E(L('فقط ۵۰۰ نتیجهٔ اخیر نمایش داده می‌شود؛ جست‌وجو را دقیق‌تر کنید.')):''}</span><nav class="product-triage-pager" aria-label="${E(L('صفحه‌بندی خبرها'))}">${Array.from({length:Math.ceil((result?.total||0)/25)},(_,index)=>`<button type="button" class="btn ${page===index?'primary':''}" data-triage-page="${index}" ${busy?'disabled':''} ${page===index?'aria-current="page"':''}>${N(index+1)}</button>`).join('')}</nav></div>`;
    $('triageSearchBtn').addEventListener('click',()=>{query=$('triageSearch').value.trim();filter=$('triageFilter').value;page=0;loadTriage();});
    $('triageSearch').addEventListener('keydown',event=>{if(event.key==='Enter'){$('triageSearchBtn').click();}});
    $('triageFilter').addEventListener('change',event=>{filter=event.target.value;query=$('triageSearch').value.trim();page=0;loadTriage();});
    $('triageRefreshBtn').addEventListener('click',()=>loadTriage());
    body.querySelectorAll('[data-triage-page]').forEach(button=>button.addEventListener('click',()=>{page=Number(button.dataset.triagePage);loadTriage();}));
    body.querySelectorAll('[data-triage-detail]').forEach(button=>button.addEventListener('click',()=>detail(rows.find(row=>row.id===button.dataset.triageDetail))));
  }
  async function loadTriage() {
    const node=mountTriage();if(!node?.open||!s()?.currentUser||!s()?.assistantId)return;
    const current=actor(),seq=++triageSerial;busy=true;paintTriage();
    try {const data=await window.req('/publications/relevance-assessments?limit=25&offset='+page*25+(filter?'&state='+encodeURIComponent(filter):'')+(query?'&query='+encodeURIComponent(query):''),{coalesceGet:false});if(seq!==triageSerial||current!==actor())return;rows=data.articles||[];result=data;busy=false;paintTriage();}
    catch(error){if(seq!==triageSerial||current!==actor())return;busy=false;const area=$('triageResults');if(area){area.setAttribute('aria-busy','false');area.innerHTML=`<div class="product-triage-error">${E(L('فهرست دریافت نشد؛ بازخوانی کنید.'))}</div>`;}}
  }
  function detail(row) {
    if(!row)return;
    const pending=row.relevance_state==='pending';
    const fields=[[L('وضعیت تصمیم'),L(labels[row.relevance_state])],[L('امتیاز AI'),pending?'—':row.relevance_score??'—'],[L('آستانهٔ مؤثر'),row.relevance_threshold??'—'],[L('اطمینان AI'),pending?'—':row.relevance_confidence??'—'],[L('موضوع'),row.relevance_topic||'—']];
    const url=String(row.source_url||'');const safeLink=/^https?:\/\//i.test(url)?`<a href="${E(url)}" target="_blank" rel="noopener noreferrer">${E(L('بازکردن خبر در منبع'))}</a>`:'';
    const body=`<div class="product-assessment-detail"><h4 data-user-content="true" dir="auto">${E(row.title)}</h4><dl>${fields.map(([key,value])=>`<dt>${E(key)}</dt><dd data-user-content="true" dir="auto">${E(value)}</dd>`).join('')}</dl>${pending?`<p>${E(L('تصمیم معتبر AI هنوز کامل نشده است؛ این خبر قابل انتشار نیست.'))}</p>`:`<h4>${E(L('دلیل تصمیم AI'))}</h4><p data-user-content="true" dir="auto">${E(row.relevance_reason)}</p>${(row.relevance_evidence||[]).map(quote=>`<blockquote data-user-content="true" dir="auto">${E(quote)}</blockquote>`).join('')}`}${safeLink}</div>`;
    window.modal(E(L('جزئیات تصمیم')),body,()=>window.closeModal(),L('بستن پنجره'));
    $('modalSubmit')?.classList.remove('primary');
    $('modalRoot')?.querySelector('.modal-foot .btn:not(#modalSubmit)')?.remove();
  }
  const originalView=window.setView;
  window.setView=function(name){const value=originalView?.apply(this,arguments);if(['overview','operations'].includes(name)){paintHealth();loadHealth();}if(name==='content'){paintTriage();if($('productTriage')?.open)loadTriage();}return value;};
  try {setView=window.setView;}catch(_){}
  const originalLoad=window.loadAll;
  window.loadAll=async function(){const value=await originalLoad?.apply(this,arguments);if(s()?.currentUser){paintHealth();loadHealth();paintTriage();if($('productTriage')?.open)loadTriage();}return value;};
  try {loadAll=window.loadAll;}catch(_){}
  const originalLanguage=window.setLanguage;
  window.setLanguage=function(){const value=originalLanguage?.apply(this,arguments);paintHealth();paintTriage();return value;};
  try {setLanguage=window.setLanguage;}catch(_){}
  window.__beeProductRefresh=()=>{paintHealth();loadHealth();paintTriage();if($('productTriage')?.open)loadTriage();};
  paintTriage();paintHealth();
})();
