
    /* MI-UX-004: make locale copy authoritative for every dynamic overview
       surface.  Renderers predate the spreadsheet catalog and used a simple
       FA/EN branch, which leaked Persian copy whenever a third locale was
       selected.  This adapter keeps data (project names, article text and
       identifiers) untouched while translating only interface labels. */
    (function(){
      const localeOverrides={
        de:{'رسانه‌های فعال':'Aktive Medien','تحلیل‌های امروز':'Heutige Analysen','انتشارها':'Veröffentlichungen','بازخورد':'Feedback','وضعیت سرویس':'Dienststatus','در دسترس و متصل':'Verfügbar und verbunden','از آخرین اجرا':'Seit dem letzten Lauf','پیش‌نویس و منتشرشده':'Entwürfe und veröffentlicht','سیگنال ثبت‌شده':'Erfasste Signale','در حال بررسی':'Wird geprüft','آماده':'Bereit','نیازمند بررسی':'Überprüfung erforderlich','سالم':'Gesund','جریان امروز':'Heutige Nachrichten','اقدام‌های پیشنهادی':'Empfohlene Maßnahmen','اولویت امروز':'Heutige Priorität','سلامت رسانه‌ها':'Mediengesundheit','مشاهده همه':'Alle anzeigen','آخرین انتشارها':'Neueste Veröffentlichungen','صف بررسی':'Warteschlange prüfen','دریافت محتوا':'Content-Ingestion','جمع‌آوری از رسانه‌های انتخاب‌شده':'Sammlung aus ausgewählten Medien','تحلیل و ارتباط‌سنجی':'Analyse und Relevanz','تفکیک واقعیت، خلاصه و ارتباط با بیزینس':'Realitätstrennung, Zusammenfassung und Geschäftsverbindung','بررسی و انتشار':'Prüfen und veröffentlichen','صف تأیید و کانال تلگرام':'Verifizierungswarteschlange und Telegram-Kanal','بررسی سلامت رسانه‌ها':'Medien-Gesundheitscheck','اجرای pipeline':'Pipeline-Ausführung','ارسال آنی یک خبر':'Nachricht jetzt veröffentlichen','امروز چه چیزی نیازمند توجه شماست؟':'Was erfordert heute Ihre Aufmerksamkeit?','فعال':'Aktiv','خودکار':'Automatisch','خاموش':'Deaktiviert','خبرهایی منتظر تأیید هستند':'Nachrichten warten auf Bestätigung','بررسی رسانه‌های ناسالم':'Nicht gesunde Medien prüfen','یک یا چند رسانه نیازمند توجه است':'Eine oder mehrere Medienquellen benötigen Aufmerksamkeit','تکمیل اتصال تلگرام':'Telegram-Verbindung abschließen','مجوز کانال بررسی شود':'Kanalberechtigungen prüfen','همه‌چیز مرتب است':'Alles ist in Ordnung','اقدام فوری وجود ندارد':'Keine dringende Maßnahme','مشاهده':'Anzeigen','رسانه‌ای برای نمایش وجود ندارد.':'Keine Medien vorhanden.','هنوز انتشاری ثبت نشده است.':'Noch keine Veröffentlichung erfasst.','Healthy':'Gesund','Needs review':'Überprüfung erforderlich','degraded':'Beeinträchtigt','healthy':'Gesund','unknown':'Unbekannt','وضعیت':'Status','آخرین خطا':'Letzter Fehler','خبر':'Nachricht','زمان':'Zeit'},
        tr:{'رسانه‌های فعال':'Etkin medya','تحلیل‌های امروز':'Bugünkü analizler','انتشارها':'Yayınlar','بازخورد':'Geri bildirim','وضعیت سرویس':'Hizmet durumu','در دسترس و متصل':'Kullanılabilir ve bağlı','از آخرین اجرا':'Son çalıştırmadan beri','پیش‌نویس و منتشرشده':'Taslak ve yayınlanan','سیگنال ثبت‌شده':'Kaydedilen sinyaller','در حال بررسی':'İnceleniyor','آماده':'Hazır','نیازمند بررسی':'İnceleme gerekli','سالم':'Sağlıklı','جریان امروز':'Bugünün akışı','اقدام‌های پیشنهادی':'Önerilen eylemler','اولویت امروز':'Bugünün önceliği','سلامت رسانه‌ها':'Medya sağlığı','مشاهده همه':'Tümünü görüntüle','آخرین انتشارها':'Son yayınlar','صف بررسی':'İnceleme kuyruğu','دریافت محتوا':'İçerik alma','تحلیل و ارتباط‌سنجی':'Analiz ve ilgi','بررسی و انتشار':'İncele ve yayınla','بررسی سلامت رسانه‌ها':'Medya sağlığını kontrol et','اجرای pipeline':'Pipeline çalıştır','ارسال آنی یک خبر':'Bir haberi şimdi yayınla','مشاهده':'Görüntüle','وضعیت':'Durum','آخرین خطا':'Son hata','خبر':'Haber','زمان':'Zaman','Healthy':'Sağlıklı','Needs review':'İnceleme gerekli','degraded':'Bozulmuş','healthy':'Sağlıklı','unknown':'Bilinmiyor'},
        ar:{'رسانه‌های فعال':'المصادر النشطة','تحلیل‌های امروز':'تحليلات اليوم','انتشارها':'المنشورات','بازخورد':'الملاحظات','وضعیت سرویس':'حالة الخدمة','در دسترس و متصل':'متاح ومتصل','از آخرین اجرا':'منذ آخر تشغيل','پیش‌نویس و منتشرشده':'مسودة ومنشور','سیگنال ثبت‌شده':'الإشارات المسجلة','در حال بررسی':'قيد المراجعة','آماده':'جاهز','نیازمند بررسی':'يتطلب المراجعة','سالم':'سليم','جریان امروز':'تدفق اليوم','اقدام‌های پیشنهادی':'الإجراءات المقترحة','اولویت امروز':'أولوية اليوم','سلامت رسانه‌ها':'سلامة المصادر','مشاهده همه':'عرض الكل','آخرین انتشارها':'أحدث المنشورات','صف بررسی':'قائمة المراجعة','دریافت محتوا':'استلام المحتوى','تحلیل و ارتباط‌سنجی':'التحليل ومدى الصلة','بررسی و انتشار':'المراجعة والنشر','بررسی سلامت رسانه‌ها':'فحص صحة المصادر','اجرای pipeline':'تشغيل خط المعالجة','ارسال آنی یک خبر':'نشر خبر الآن','مشاهده':'عرض','وضعیت':'الحالة','آخرین خطا':'آخر خطأ','خبر':'الخبر','زمان':'الوقت','Healthy':'سليم','Needs review':'يتطلب المراجعة','degraded':'متدهور','healthy':'سليم','unknown':'غير معروف'},
        es:{'رسانه‌های فعال':'Medios activos','تحلیل‌های امروز':'Análisis de hoy','انتشارها':'Publicaciones','بازخورد':'Comentarios','وضعیت سرویس':'Estado del servicio','در دسترس و متصل':'Disponible y conectado','از آخرین اجرا':'Desde la última ejecución','پیش‌نویس و منتشرشده':'Borradores y publicados','سیگنال ثبت‌شده':'Señales registradas','در حال بررسی':'En revisión','آماده':'Listo','نیازمند بررسی':'Requiere revisión','سالم':'Saludable','جریان امروز':'Flujo de hoy','اقدام‌های پیشنهادی':'Acciones sugeridas','اولویت امروز':'Prioridad de hoy','سلامت رسانه‌ها':'Salud de medios','مشاهده همه':'Ver todo','آخرین انتشارها':'Publicaciones más recientes','صف بررسی':'Cola de revisión','دریافت محتوا':'Ingesta de contenido','تحلیل و ارتباط‌سنجی':'Análisis y relevancia','بررسی و انتشار':'Revisar y publicar','بررسی سلامت رسانه‌ها':'Comprobar salud de medios','اجرای pipeline':'Ejecutar pipeline','ارسال آنی یک خبر':'Publicar una noticia ahora','مشاهده':'Ver','وضعیت':'Estado','آخرین خطا':'Último error','خبر':'Noticia','زمان':'Hora','Healthy':'Saludable','Needs review':'Requiere revisión','degraded':'Degradado','healthy':'Saludable','unknown':'Desconocido'},
        it:{'رسانه‌های فعال':'Media attivi','تحلیل‌های امروز':'Analisi di oggi','انتشارها':'Pubblicazioni','بازخورد':'Feedback','وضعیت سرویس':'Stato del servizio','در دسترس و متصل':'Disponibile e connesso','از آخرین اجرا':'Dall’ultima esecuzione','پیش‌نویس و منتشرشده':'Bozze e pubblicati','سیگنال ثبت‌شده':'Segnali registrati','در حال بررسی':'In revisione','آماده':'Pronto','نیازمند بررسی':'Richiede revisione','سالم':'In salute','جریان امروز':'Flusso di oggi','اقدام‌های پیشنهادی':'Azioni suggerite','اولویت امروز':'Priorità di oggi','سلامت رسانه‌ها':'Salute dei media','مشاهده همه':'Visualizza tutto','آخرین انتشارها':'Pubblicazioni recenti','صف بررسی':'Coda di revisione','دریافت محتوا':'Acquisizione contenuti','تحلیل و ارتباط‌سنجی':'Analisi e pertinenza','بررسی و انتشار':'Rivedi e pubblica','بررسی سلامت رسانه‌ها':'Controlla salute media','اجرای pipeline':'Esegui pipeline','ارسال آنی یک خبر':'Pubblica subito una notizia','مشاهده':'Visualizza','وضعیت':'Stato','آخرین خطا':'Ultimo errore','خبر':'Notizia','زمان':'Ora','Healthy':'In salute','Needs review':'Richiede revisione','degraded':'Degradato','healthy':'In salute','unknown':'Sconosciuto'},
        fr:{'رسانه‌های فعال':'Médias actifs','تحلیل‌های امروز':'Analyses du jour','انتشارها':'Publications','بازخورد':'Commentaires','وضعیت سرویس':'État du service','در دسترس و متصل':'Disponible et connecté','از آخرین اجرا':'Depuis la dernière exécution','پیش‌نویس و منتشرشده':'Brouillons et publiés','سیگنال ثبت‌شده':'Signaux enregistrés','در حال بررسی':'En cours de vérification','آماده':'Prêt','نیازمند بررسی':'Vérification requise','سالم':'Sain','جریان امروز':'Flux du jour','اقدام‌های پیشنهادی':'Actions suggérées','اولویت امروز':'Priorité du jour','سلامت رسانه‌ها':'Santé des médias','مشاهده همه':'Tout afficher','آخرین انتشارها':'Dernières publications','صف بررسی':'File de vérification','دریافت محتوا':'Collecte de contenu','تحلیل و ارتباط‌سنجی':'Analyse et pertinence','بررسی و انتشار':'Vérifier et publier','بررسی سلامت رسانه‌ها':'Vérifier la santé des médias','اجرای pipeline':'Exécuter le pipeline','ارسال آنی یک خبر':'Publier une actualité maintenant','مشاهده':'Afficher','وضعیت':'État','آخرین خطا':'Dernière erreur','خبر':'Actualité','زمان':'Heure','Healthy':'Sain','Needs review':'Vérification requise','degraded':'Dégradé','healthy':'Sain','unknown':'Inconnu'}
      };
      window.__miLocaleOverrides=localeOverrides;
      // Arabic and Persian share the Arabic Unicode block.  Treat only
      // Persian-specific code points as an untranslated Persian signal;
      // otherwise valid Arabic copy is incorrectly rejected and replaced by
      // an English fallback.
      const persian=/[\u067e\u0686\u0698\u06af\u06cc\u06a9\u06f0-\u06f9]/;
      const valid=v=>{const text=String(v??'').trim();return Boolean(text&&text!=='—'&&text!=='Loading...'&&!persian.test(text))};
      const keyOf=value=>{const raw=String(value??'').trim();try{return uxCopyKey(raw)}catch(_){return raw}};
      const label=(source,fallback='')=>{
        const raw=String(source??'').trim(),key=keyOf(raw),row=uxWritingCatalog[key];
        const direct=window.__miLocaleOverrides?.[state.language]?.[raw]||window.__miLocaleOverrides?.[state.language]?.[key];
        if(valid(direct))return direct;
        const catalog=row?.[state.language];if(valid(catalog))return catalog;
        const local=localeCopy[state.language]?.[key]||localeCopy[state.language]?.[raw];if(valid(local))return local;
        const english=row?.en||copyMap[key]||copyMap[raw]||fallback;if(state.language==='fa')return row?.fa||raw;
        return valid(english)?english:(persian.test(raw)?fallback||'—':raw);
      };
      window.__miLabel=label;
      const setText=(node,value)=>{if(node&&value&&node.textContent!==value)node.textContent=value};
      const replaceFirstText=(node,value)=>{if(!node)return;const next=value+' ';for(const child of node.childNodes){if(child.nodeType===Node.TEXT_NODE){if(child.nodeValue!==next)child.nodeValue=next;return}}node.insertBefore(document.createTextNode(next),node.firstChild)};
      function dashboard(){
        const root=document.querySelector('#view-overview');if(!root)return;
        const labels=['رسانه‌های فعال','تحلیل‌های امروز','انتشارها','بازخورد','وضعیت سرویس'];
        root.querySelectorAll('.kpi-label').forEach((node,i)=>{if(labels[i])replaceFirstText(node,label(labels[i]))});
        const notes=['در دسترس و متصل','از آخرین اجرا','پیش‌نویس و منتشرشده','سیگنال ثبت‌شده'];
        root.querySelectorAll('.kpi-note').forEach((node,i)=>{if(notes[i])setText(node,label(notes[i]))});
        setText(root.querySelector('#kpiHealth'),label(root.querySelector('#kpiHealth')?.textContent==='آماده'?'آماده':root.querySelector('#kpiHealth')?.textContent==='سالم'?'سالم':'نیازمند بررسی'));
        const serviceNote=root.querySelector('#kpiHealthNote');if(serviceNote){const raw=serviceNote.textContent.trim();const source=raw.includes('تلگرام')?'سرویس سالم است؛ تلگرام نیازمند بررسی است':raw.includes('کانال')?'سرویس و کانال بررسی شده':raw==='—'?'سرویس سالم است':raw;setText(serviceNote,label(source,raw))}
        const title=root.querySelector('.page-head h2');if(title)setText(title,label('نمای کلی'));
        const subtitle=root.querySelector('.page-head p');if(subtitle)setText(subtitle,label('امروز چه چیزی نیازمند توجه شماست؟'));
        setText(root.querySelector('#healthProbeBtn'),label('بررسی سلامت رسانه‌ها'));
        setText(root.querySelector('#runPipelineBtn'),label('اجرای pipeline'));
        setText(root.querySelector('#manualPublishBtn'),label('ارسال آنی یک خبر'));
        const flow=[['دریافت محتوا','جمع‌آوری از رسانه‌های انتخاب‌شده'],['تحلیل و ارتباط‌سنجی','تفکیک واقعیت، خلاصه و ارتباط با بیزینس'],['بررسی و انتشار','صف تأیید و کانال تلگرام']];
        root.querySelectorAll('.timeline-row').forEach((row,i)=>{const item=flow[i];if(!item)return;setText(row.querySelector('b'),label(item[0]));setText(row.querySelector('small'),label(item[1]));const stateNode=row.querySelector('strong');if(stateNode){const raw=stateNode.textContent.trim();const source=raw==='فعال'?'فعال':raw==='خودکار'?'خودکار':raw==='خاموش'?'خاموش':raw;setText(stateNode,label(source,raw))}});
        const flowTitle=root.querySelector('.timeline')?.closest('.section-card')?.querySelector('.section-title h3');if(flowTitle)setText(flowTitle,label('جریان امروز'));
        const actionCard=root.querySelector('#nextActions')?.closest('.section-card');if(actionCard){setText(actionCard.querySelector('.section-title h3'),label('اقدام‌های پیشنهادی'));setText(actionCard.querySelector('.section-title span'),label('اولویت امروز'));const specs=[['صف بررسی خبر','خبرهایی منتظر تأیید هستند'],['بررسی رسانه‌های ناسالم','یک یا چند رسانه نیازمند توجه است'],['تکمیل اتصال تلگرام','مجوز کانال بررسی شود'],['همه‌چیز مرتب است','اقدام فوری وجود ندارد']];actionCard.querySelectorAll('#nextActions .detail-item').forEach((row,i)=>{const spec=specs[i];if(!spec)return;setText(row.querySelector('b'),label(spec[0]));setText(row.querySelector('.muted'),label(spec[1]));setText(row.querySelector('.btn'),label('مشاهده'))})}
        const cards=root.querySelectorAll('.grid.two-col.mt-14 .section-card');if(cards.length>=2){setText(cards[0].querySelector('.section-title h3'),label('سلامت رسانه‌ها'));setText(cards[0].querySelector('.section-title button'),label('مشاهده همه'));setText(cards[1].querySelector('.section-title h3'),label('آخرین انتشارها'));setText(cards[1].querySelector('.section-title button'),label('صف بررسی'));cards.forEach(card=>card.querySelectorAll('thead th').forEach((th,i)=>{const k=['رسانه','وضعیت','آخرین خطا','خبر','وضعیت','زمان'][i];if(k)setText(th,label(k))}))}
        root.querySelectorAll('.source-health').forEach(node=>{const raw=node.textContent.trim(),value=label(raw,raw);if(raw===value)return;for(const child of [...node.childNodes])if(child.nodeType===Node.TEXT_NODE)child.remove();node.appendChild(document.createTextNode(value))});
        root.querySelectorAll('.status').forEach(node=>{const raw=node.textContent.trim();const value=label(raw,raw);if(value!==raw)setText(node,value)});
        const updated=root.querySelector('#pipelineUpdated');if(updated)updated.textContent='';
      }
      function scrub(){
        if(state.language==='fa')return;
        // First resolve English aliases through the sheet catalog (some
        // legacy renderers use English for every non-FA locale), then scrub
        // any Persian fallback that remains in a user-facing label.
        try{translateStaticCopy()}catch(_){ }
        document.querySelectorAll('#app h1,#app h2,#app h3,#app h4,#app p,#app label,#app button,#app .nav-text,#app .notice,#app .kpi-label,#app .kpi-note,#app .section-title span,#app .muted,#app th').forEach(node=>{
          // Article titles, source names, project names and error details are
          // user/source data, not UX Writing.  Leave those values in their
          // original language even when the shell locale changes.
          if(node.children.length||node.closest('[data-language-select]')||node.closest(reportProseSelector)||node.closest('#recentRows,#publicationRows,#healthRows,#sourceRows,#topicRows,#assistantGrid,#businessSummary,#telegramDetails,#userRows,#sessionRows'))return;
          const raw=node.dataset.miFaText||node.textContent.trim();if(!raw||!persian.test(raw))return;const translated=label(raw);if(valid(translated)){node.dataset.miFaText=raw;setText(node,translated)}
        });
        dashboard();
      }
      // Do not observe the whole document here.  This pass used to run every
      // 35ms after any text mutation (including its own writes), racing with
      // renderers and repainting copy in different locales.  Locale changes
      // and newly-rendered views now call the explicit, serialized controller
      // installed at the end of the document.
      window.__researchBeeLocaleDashboard=dashboard;
      window.__researchBeeRunLocaleScrub=scrub;
      scrub();
    })();
