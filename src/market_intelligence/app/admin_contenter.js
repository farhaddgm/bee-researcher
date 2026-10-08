/* Read-only external connection. AI use requires a separate research-context approval. */
(() => {
  if (window.__beeContenter) return;
  window.__beeContenter = true;
  const COPY = {
    fa: ['کسب‌وکار متصل از Contenter','اتصال و همگام‌سازی خودکار، قواعد تحلیل را تغییر نمی‌دهند. استفاده در AI فقط از بخش زمینهٔ کسب‌وکار و با پیش‌نمایش و تأیید جداگانه فعال می‌شود.','کسب‌وکاری از Contenter متصل نشده است.','انتخاب کسب‌وکار','همگام‌سازی','جداکردن اتصال','مشاهده پروفایل','باز کردن در Contenter','جست‌وجوی نام یا حوزهٔ کسب‌وکار','اتصال','بستن','در حال دریافت…','اتصال روی سرور پیکربندی نشده است.','فقط مالک','آزمون اتصال','همگام','نسخهٔ ذخیره‌شده؛ اتصال موقتاً در دسترس نیست','دسترسی لغو شده','کسب‌وکار در دسترس نیست','بایگانی‌شده','نسخهٔ ذخیره‌شده منقضی شده','آخرین همگام‌سازی','نسخه','اتصال یا دریافت اطلاعات ناموفق بود؛ دوباره تلاش کنید.','اتصال این پروژه جدا شود؟ پروفایل محلی و تنظیمات ربات تغییر نمی‌کنند.','فقط‌خواندنی','تاریخچه نسخه‌ها','قبلی','بعدی','کسب‌وکاری با این جست‌وجو پیدا نشد.','اتصال به Contenter','واقعیت‌های کلیدی','واژه‌نامه برند','یادداشت‌ها','منابع مرجع','دارایی‌های برند','آزمون موفق بود','آخرین نسخهٔ دریافتی','هیچ موردی ثبت نشده است.'],
    en: ['Business linked from Contenter','Linking and automatic sync do not change analysis rules. AI use is enabled separately through the business-context preview and approval.','No Contenter business is linked.','Choose business','Synchronize','Unlink','View profile','Open in Contenter','Search business name or industry','Link','Close','Loading…','The connection is not configured on the server.','Owners only','Test connection','In sync','Cached version; connection temporarily unavailable','Access revoked','Business unavailable','Archived','Cached version expired','Last synchronized','Version','Connection or data retrieval failed; please try again.','Unlink this project? Local profiles and bot settings will remain unchanged.','Read-only','Version history','Previous','Next','No business matches this search.','Contenter connection','Key facts','Brand terminology','Notes','References','Brand assets','Connection test passed','Latest received version','No items recorded.'],
    tr: ['Contenter’dan bağlı işletme','Bağlantı ve otomatik eşitleme analiz kurallarını değiştirmez. AI kullanımı, işletme bağlamı önizlemesi ve ayrı onayla etkinleştirilir.','Contenter’dan bir işletme bağlı değil.','İşletme seç','Eşitle','Bağlantıyı kaldır','Profili görüntüle','Contenter’da aç','İşletme adı veya sektör ara','Bağla','Kapat','Yükleniyor…','Sunucuda bağlantı yapılandırılmadı.','Yalnızca sahip','Bağlantıyı test et','Eşitlenmiş','Kayıtlı sürüm; bağlantı geçici olarak kullanılamıyor','Erişim iptal edildi','İşletmeye erişilemiyor','Arşivlenmiş','Kayıtlı sürümün süresi doldu','Son eşitleme','Sürüm','Bağlantı veya veri alma başarısız oldu; tekrar deneyin.','Bu projenin bağlantısı kaldırılsın mı? Yerel profiller ve bot ayarları değişmez.','Salt okunur','Sürüm geçmişi','Önceki','Sonraki','Bu aramaya uygun işletme bulunamadı.','Contenter bağlantısı','Temel bilgiler','Marka terminolojisi','Notlar','Referanslar','Marka varlıkları','Bağlantı testi başarılı','Son alınan sürüm','Kayıtlı öğe yok.'],
    ar: ['النشاط التجاري المرتبط من Contenter','الربط والمزامنة التلقائية لا يغيّران قواعد التحليل. يُفعّل الاستخدام في AI بصورة منفصلة عبر معاينة سياق الأعمال واعتماده.','لا يوجد نشاط تجاري مرتبط من Contenter.','اختيار نشاط تجاري','مزامنة','إلغاء الربط','عرض الملف','فتح في Contenter','البحث باسم النشاط التجاري أو مجاله','ربط','إغلاق','جارٍ التحميل…','الاتصال غير مُعدّ على الخادم.','للمالك فقط','اختبار الاتصال','تمت المزامنة','نسخة محفوظة؛ الاتصال غير متاح مؤقتًا','أُلغي الوصول','النشاط التجاري غير متاح','مؤرشف','انتهت صلاحية النسخة المحفوظة','آخر مزامنة','الإصدار','تعذّر الاتصال أو جلب البيانات؛ يُرجى المحاولة مجددًا.','هل تريد إلغاء ربط هذا المشروع؟ لن تتغير الملفات المحلية أو إعدادات الروبوت.','للقراءة فقط','سجل الإصدارات','السابق','التالي','لا يوجد نشاط تجاري يطابق هذا البحث.','الاتصال بـ Contenter','الحقائق الأساسية','مصطلحات العلامة التجارية','الملاحظات','المراجع','أصول العلامة التجارية','نجح اختبار الاتصال','آخر إصدار تم استلامه','لا توجد عناصر مسجلة.'],
    es: ['Empresa vinculada desde Contenter','La vinculación y la sincronización automática no cambian las reglas de análisis. El uso en IA se activa por separado mediante una vista previa y aprobación del contexto empresarial.','No hay una empresa de Contenter vinculada.','Elegir empresa','Sincronizar','Desvincular','Ver perfil','Abrir en Contenter','Buscar nombre o sector de la empresa','Vincular','Cerrar','Cargando…','La conexión no está configurada en el servidor.','Solo propietarios','Probar conexión','Sincronizado','Versión guardada; conexión no disponible temporalmente','Acceso revocado','Empresa no disponible','Archivada','La versión guardada ha caducado','Última sincronización','Versión','Falló la conexión o la consulta; vuelve a intentarlo.','¿Desvincular este proyecto? Los perfiles locales y ajustes del bot no cambiarán.','Solo lectura','Historial de versiones','Anterior','Siguiente','Ninguna empresa coincide con esta búsqueda.','Conexión con Contenter','Datos clave','Terminología de marca','Notas','Referencias','Recursos de marca','Prueba de conexión correcta','Última versión recibida','No hay elementos registrados.'],
    it: ['Attività collegata da Contenter','Il collegamento e la sincronizzazione automatica non cambiano le regole di analisi. L’uso in AI si attiva separatamente tramite anteprima e approvazione del contesto aziendale.','Nessuna attività di Contenter collegata.','Scegli attività','Sincronizza','Scollega','Visualizza profilo','Apri in Contenter','Cerca nome o settore dell’attività','Collega','Chiudi','Caricamento…','La connessione non è configurata sul server.','Solo proprietari','Verifica connessione','Sincronizzato','Versione salvata; connessione temporaneamente non disponibile','Accesso revocato','Attività non disponibile','Archiviata','La versione salvata è scaduta','Ultima sincronizzazione','Versione','Connessione o recupero dati non riuscito; riprova.','Scollegare questo progetto? I profili locali e le impostazioni del bot non cambieranno.','Sola lettura','Cronologia versioni','Precedente','Successiva','Nessuna attività corrisponde alla ricerca.','Connessione a Contenter','Dati principali','Terminologia del marchio','Note','Riferimenti','Risorse del marchio','Verifica della connessione riuscita','Ultima versione ricevuta','Nessun elemento registrato.'],
    de: ['Verknüpftes Unternehmen aus Contenter','Verknüpfung und automatische Synchronisierung ändern keine Analyseregeln. Die KI-Nutzung wird separat durch Vorschau und Freigabe des Geschäftskontexts aktiviert.','Kein Contenter-Unternehmen verknüpft.','Unternehmen auswählen','Synchronisieren','Verknüpfung lösen','Profil ansehen','In Contenter öffnen','Unternehmensname oder Branche suchen','Verknüpfen','Schließen','Wird geladen…','Die Verbindung ist auf dem Server nicht eingerichtet.','Nur Eigentümer','Verbindung testen','Synchronisiert','Gespeicherte Version; Verbindung vorübergehend nicht verfügbar','Zugriff widerrufen','Unternehmen nicht verfügbar','Archiviert','Gespeicherte Version abgelaufen','Zuletzt synchronisiert','Version','Verbindung oder Datenabruf fehlgeschlagen; bitte erneut versuchen.','Dieses Projekt trennen? Lokale Profile und Bot-Einstellungen bleiben unverändert.','Schreibgeschützt','Versionsverlauf','Zurück','Weiter','Kein Unternehmen entspricht dieser Suche.','Contenter-Verbindung','Wichtige Fakten','Markenterminologie','Notizen','Referenzen','Markenmaterialien','Verbindungstest erfolgreich','Zuletzt empfangene Version','Keine Einträge vorhanden.'],
    fr: ['Entreprise liée depuis Contenter','La liaison et la synchronisation automatique ne modifient pas les règles d’analyse. L’utilisation par l’IA est activée séparément après aperçu et approbation du contexte métier.','Aucune entreprise Contenter n’est liée.','Choisir une entreprise','Synchroniser','Délier','Voir le profil','Ouvrir dans Contenter','Rechercher un nom ou un secteur d’activité','Lier','Fermer','Chargement…','La connexion n’est pas configurée sur le serveur.','Propriétaires uniquement','Tester la connexion','Synchronisé','Version enregistrée ; connexion temporairement indisponible','Accès révoqué','Entreprise indisponible','Archivée','La version enregistrée a expiré','Dernière synchronisation','Version','Échec de connexion ou de récupération ; veuillez réessayer.','Délier ce projet ? Les profils locaux et les paramètres du robot resteront inchangés.','Lecture seule','Historique des versions','Précédent','Suivant','Aucune entreprise ne correspond à cette recherche.','Connexion à Contenter','Informations clés','Terminologie de marque','Notes','Références','Ressources de marque','Test de connexion réussi','Dernière version reçue','Aucun élément enregistré.']
  };
  const SECTIONS = {
    fa: ['معرفی','محصولات و خدمات','بازار هدف','پرسوناها','ارزش پیشنهادی','رقبا','لحن برند','برندبوک','پیام‌های کلیدی','ستون‌های محتوایی','قواعد و محدودیت‌ها','کانال‌ها','اهداف','پرسش‌های مشتری','تقویم'],
    en: ['Overview','Products and services','Target market','Personas','Value proposition','Competitors','Brand voice','Brand book','Key messages','Content pillars','Rules and constraints','Channels','Goals','Customer questions','Calendar'],
    tr: ['Genel bilgiler','Ürünler ve hizmetler','Hedef pazar','Personalar','Değer önerisi','Rakipler','Marka sesi','Marka kılavuzu','Temel mesajlar','İçerik temaları','Kurallar ve kısıtlar','Kanallar','Hedefler','Müşteri soruları','Takvim'],
    ar: ['التعريف','المنتجات والخدمات','السوق المستهدف','شخصيات العملاء','القيمة المقترحة','المنافسون','نبرة العلامة','دليل العلامة','الرسائل الأساسية','محاور المحتوى','القواعد والقيود','القنوات','الأهداف','أسئلة العملاء','التقويم'],
    es: ['Presentación','Productos y servicios','Mercado objetivo','Perfiles de clientes','Propuesta de valor','Competidores','Voz de marca','Manual de marca','Mensajes clave','Pilares de contenido','Reglas y restricciones','Canales','Objetivos','Preguntas de clientes','Calendario'],
    it: ['Presentazione','Prodotti e servizi','Mercato di riferimento','Profili dei clienti','Proposta di valore','Concorrenti','Voce del marchio','Manuale del marchio','Messaggi chiave','Pilastri dei contenuti','Regole e vincoli','Canali','Obiettivi','Domande dei clienti','Calendario'],
    de: ['Überblick','Produkte und Dienstleistungen','Zielmarkt','Kundenprofile','Wertversprechen','Wettbewerber','Markenstimme','Markenhandbuch','Kernbotschaften','Inhaltssäulen','Regeln und Einschränkungen','Kanäle','Ziele','Kundenfragen','Kalender'],
    fr: ['Présentation','Produits et services','Marché cible','Profils clients','Proposition de valeur','Concurrents','Voix de marque','Guide de marque','Messages clés','Piliers de contenu','Règles et contraintes','Canaux','Objectifs','Questions des clients','Calendrier']
  };
  const CONFIGURED = {fa:'اتصال پیکربندی شده؛ برای بررسی سلامت آزمون را اجرا کنید.',en:'Configured; run the test to verify connectivity.',tr:'Yapılandırıldı; bağlantıyı doğrulamak için testi çalıştırın.',ar:'الاتصال مُعدّ؛ شغّل الاختبار للتحقق منه.',es:'Configurada; ejecuta la prueba para verificar la conexión.',it:'Configurata; esegui il test per verificare la connessione.',de:'Konfiguriert; führen Sie den Verbindungstest aus.',fr:'Configurée ; lancez le test pour vérifier la connexion.'};
  const keys = ['OVERVIEW','SERVICES','TARGET_MARKET','PERSONAS','VALUE_PROPOSITION','COMPETITORS','BRAND_VOICE','BRAND_BOOK','KEY_MESSAGES','CONTENT_PILLARS','GUIDELINES','CHANNELS','GOALS','FAQ','CALENDAR'];
  const S = () => window.__researchBeeState;
  const L = i => (COPY[S()?.language] || COPY.en)[i];
  const E = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const owner = () => Boolean(S()?.currentUser?.is_owner || S()?.currentUser?.role === 'owner');
  const write = () => owner() || (loadedActor === actor() && data?.can_write === true);
  const actor = () => S()?.currentUser?.id + ':' + S()?.assistantId;
  const path = id => '/admin/api/assistants/' + encodeURIComponent(id) + '/contenter';
  let data = null, loadedActor = '', loadingActor = '', seq = 0, busy = false, settingsData = null;
  const date = value => value ? new Date(value).toLocaleString(S()?.language || 'en') : '—';
  function card(root, id) {
    if (!root) return null;
    let panel = document.getElementById(id);
    if (!panel) {
      panel = document.createElement('section'); panel.id = id; panel.className = 'card section-card contenter-card'; panel.dataset.dynamicCopy = '';
      const heading = root.id === 'view-businesses' ? root.querySelector('.page-head') : null;
      if (heading) heading.after(panel); else root.appendChild(panel);
    }
    return panel;
  }
  function showModal(title, body) {
    window.modal(E(title), body, window.closeModal, L(10));
    const dialog = document.getElementById('modalRoot').querySelector('[role=dialog]');
    dialog.dataset.contenterActor = actor();
    dialog.querySelector('#modalSubmit')?.classList.remove('primary');
    dialog.querySelector('.modal-foot .btn:not(#modalSubmit)')?.remove();
    return dialog;
  }
  function paint() {
    const panel = card(document.getElementById('view-businesses'), 'contenterBusinessCard');
    if (!panel) return;
    const current = loadedActor === actor() ? data : null;
    panel.dataset.loadedAssistant = current ? S().assistantId : '';
    const states = {healthy:15,stale:16,access_revoked:17,unavailable:18,archived:19,expired:20};
    const button = (action,label,primary=false) => `<button type="button" class="btn${primary?' primary':''}" data-contenter-action="${action}" ${busy||!current?'disabled':''}>${E(L(label))}</button>`;
    panel.innerHTML = `<div class="section-title"><h3>${E(L(0))}</h3><span class="status">${E(L(25))}</span></div><p class="notice">${E(L(1))}</p>${current?.linked?`<h4 data-user-content="true" dir="auto">${E(current.business_name)}</h4><p role="status">${E(L(states[current.state] ?? 18))}</p><dl class="contenter-meta"><div><dt>${E(L(21))}</dt><dd>${E(date(current.last_success_at))}</dd></div><div><dt>${E(L(22))}</dt><dd>${E(current.version)}</dd></div></dl>`:`<p class="muted" role="status">${E(L(loadingActor===actor()?11:2))}</p>`}<div class="card-actions">${current?.profile?button('profile',6)+button('versions',26):''}${current?.open_url?`<a class="btn" href="${E(current.open_url)}" target="_blank" rel="noopener noreferrer">${E(L(7))}</a>`:''}${write()&&S()?.assistantId?`${current?.linked?button('sync',4)+button('unlink',5):''}${button('choose',3,true)}`:''}</div>`;
    panel.querySelectorAll('[data-contenter-action]').forEach(node => node.addEventListener('click', () => action(node.dataset.contenterAction)));
    const settingsPanel = card(document.getElementById('view-settings'), 'contenterConnectionCard');
    if (!settingsPanel) return;
    settingsPanel.hidden = !owner();
    settingsPanel.dataset.ownerOnly = 'true';
    if (!owner()) { settingsPanel.replaceChildren(); settingsData = null; return; }
    settingsPanel.innerHTML = `<div class="section-title"><h3>${E(L(30))}</h3><span class="status">${E(L(13))}</span></div><p class="notice">${E(L(1))}</p><p role="status">${E(settingsData?.configured?(CONFIGURED[S()?.language]||CONFIGURED.en):L(12))}</p><div class="card-actions"><button type="button" class="btn" id="contenterTestBtn" ${busy?'disabled':''}>${E(L(14))}</button></div>`;
    document.getElementById('contenterTestBtn').addEventListener('click', async () => {
      if (busy || !owner()) return; const currentActor=actor(); busy=true; paint();
      try { const result=await window.req('/admin/api/contenter/test',{method:'POST'}); if(currentActor===actor())window.toast(L(result.state==='healthy'?36:23),result.state!=='healthy'); }
      catch (_) { if(currentActor===actor())window.toast(L(23),true); } finally {busy=false;paint();}
    });
  }
  async function load(force=false) {
    const dialog=document.querySelector('#modalRoot [data-contenter-actor]');
    if(dialog && dialog.dataset.contenterActor!==actor())window.closeModal();
    if (!S()?.currentUser || !S()?.assistantId) {loadedActor='';data=null;paint();return;}
    const visible=document.querySelector('.view.active')?.id;
    if (!['view-businesses','view-settings'].includes(visible)) return;
    const current=actor(),id=S().assistantId;
    if (loadingActor===current || (!force&&loadedActor===current)) {paint();return;}
    const serial=++seq;loadingActor=current;paint();
    try {
      const [link,status]=await Promise.all([window.req(path(id),{coalesceGet:false}),owner()?window.req('/admin/api/contenter/status',{coalesceGet:false}):Promise.resolve(null)]);
      if(serial!==seq||current!==actor())return;
      data=link;settingsData=status;loadedActor=current;
    } catch (_) {if(serial===seq&&current===actor()){data=null;loadedActor=current;window.toast(L(23),true);}}
    finally {if(serial===seq){loadingActor='';paint();}}
  }
  function viewProfile() {
    const profile=data?.profile;
    if (!profile) return;
    const sectionNames=SECTIONS[S()?.language]||SECTIONS.en;
    const content=(profile.sections||[]).map(section=>`<section><h4>${E(sectionNames[keys.indexOf(section.key)]||section.key)}</h4><div class="contenter-prose" data-user-content="true" dir="auto">${E(section.content||'—')}</div></section>`).join('');
    const groups=[['facts',31],['terms',32],['notes',33],['references',34],['assets',35]].map(([key,title])=>`<section><h4>${E(L(title))}</h4>${(profile[key]||[]).map(item=>`<div class="contenter-prose" data-user-content="true" dir="auto">${E([item.label||item.term||item.title||'',item.value||item.text||item.excerpt||item.description||'',item.analysis?.summary||''].filter(Boolean).join('\n'))}</div>`).join('')||`<p>${E(L(38))}</p>`}</section>`).join('');
    showModal(data.business_name,`<div class="contenter-profile" data-dynamic-copy><p class="notice">${E(L(1))}</p>${content}${groups}</div>`).dataset.contenterProfile='';
  }
  async function choose() {
    const id=S()?.assistantId,currentActor=actor();if(!id||!write())return;
    showModal(L(3),`<div class="contenter-picker" data-dynamic-copy><div class="form-grid"><label class="field full">${E(L(8))}<input id="contenterSearch" type="search" maxlength="200"></label></div><div class="card-actions"><button type="button" class="btn" id="contenterSearchBtn">${E(L(8))}</button></div><div id="contenterChoices" aria-live="polite"></div><div class="card-actions"><button type="button" class="btn" id="contenterPrevious">${E(L(27))}</button><span id="contenterPage"></span><button type="button" class="btn" id="contenterNext">${E(L(28))}</button></div></div>`);
    const picker=document.getElementById('modalRoot').querySelector('.contenter-picker');
    let page=1,totalPages=1,searchSerial=0;
    async function search() {
      const serial=++searchSerial,query=picker.querySelector('#contenterSearch').value;
      picker.querySelector('#contenterChoices').textContent=L(11);
      picker.querySelectorAll('button').forEach(x=>x.disabled=true);
      try {
        const result=await window.req(path(id)+'/businesses?q='+encodeURIComponent(query)+'&page='+page,{coalesceGet:false});
        if(serial!==searchSerial||currentActor!==actor()||!picker.isConnected)return;
        totalPages=result.total_pages;
        picker.querySelector('#contenterChoices').innerHTML=result.items.map(item=>`<article class="contenter-choice"><div data-user-content="true" dir="auto"><strong>${E(item.name)}</strong><p>${E(item.industry)}</p></div><button type="button" class="btn primary" data-link-business="${E(item.id)}" ${item.status!=='ACTIVE'?'disabled':''}>${E(L(9))}</button></article>`).join('')||`<p role="status">${E(L(29))}</p>`;
        picker.querySelectorAll('[data-link-business]').forEach(button=>button.addEventListener('click',async()=>{
          if(busy||currentActor!==actor())return;busy=true;button.disabled=true;
          try {const result=await window.req(path(id),{method:'PUT',body:JSON.stringify({business_id:button.dataset.linkBusiness})});if(currentActor===actor()){data=result;loadedActor=currentActor;window.closeModal();document.dispatchEvent(new Event('contenter-link-updated'));}}
          catch (_){if(currentActor===actor())window.toast(L(23),true);}finally{busy=false;if(button.isConnected)button.disabled=false;paint();}
        }));
        picker.querySelector('#contenterPage').textContent=page+' / '+totalPages;
      } catch (error) {if(picker.isConnected&&currentActor===actor())picker.querySelector('#contenterChoices').textContent=L(error.message?.includes('not_configured')?12:23);}
      finally {if(serial===searchSerial&&picker.isConnected){picker.querySelector('#contenterSearchBtn').disabled=false;picker.querySelector('#contenterPrevious').disabled=page<=1;picker.querySelector('#contenterNext').disabled=page>=totalPages;}}
    }
    picker.querySelector('#contenterSearchBtn').addEventListener('click',()=>{page=1;search();});
    picker.querySelector('#contenterSearch').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();page=1;search();}});
    picker.querySelector('#contenterPrevious').addEventListener('click',()=>{page--;search();});
    picker.querySelector('#contenterNext').addEventListener('click',()=>{page++;search();});
    await search();
  }
  async function action(kind) {
    if(loadedActor!==actor())return;
    if(kind==='profile'){viewProfile();return;}
    if(kind==='choose'){await choose();return;}
    const id=S()?.assistantId,currentActor=actor();if(!id||busy)return;
    if(kind==='unlink'&&!confirm(L(24)))return;
    busy=true;paint();
    try {
      if(kind==='versions') {
        const result=await window.req(path(id)+'/versions',{coalesceGet:false});
        if(currentActor===actor())showModal(L(26),`<div class="contenter-profile" data-dynamic-copy>${result.items.map(item=>`<div class="contenter-choice"><span>${E(L(22))} ${E(item.version)} · ${E(date(item.created_at))}</span><code>${E(item.content_hash.slice(0,12))}</code></div>`).join('')}</div>`);
      } else {
        const result=await window.req(path(id)+(kind==='sync'?'/sync':''),{method:kind==='sync'?'POST':'DELETE'});
        if(currentActor===actor()){data=result;loadedActor=currentActor;document.dispatchEvent(new Event('contenter-link-updated'));}
      }
    } catch (_) {if(currentActor===actor())window.toast(L(23),true);}finally{busy=false;paint();}
  }
  for(const [name,refresh] of [['setView',false],['setLanguage',false],['loadAll',true],['refreshBusinessUi',true]]) {
    const prior=window[name];if(typeof prior!=='function')continue;
    window[name]=function(){const result=prior.apply(this,arguments);if(result?.then)result.then(()=>load(refresh),()=>load(refresh));else load(refresh);return result;};
  }
  // Global function declarations are the same window properties, including existing callbacks.
  paint();load();
})();
