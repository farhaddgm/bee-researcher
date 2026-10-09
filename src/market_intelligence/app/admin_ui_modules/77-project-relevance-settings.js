
    (function(){
      const texts={
        fa:['ارتباط‌سنجی خبر','حداقل امتیاز ارتباط پروژه','خبر باید هم به این آستانه و هم به آستانهٔ موضوع برسد. امتیاز هوش مصنوعی پیش از انتخاب خبر محاسبه می‌شود.','ذخیره','تحلیل هوش مصنوعی فعال است','تحلیل هوش مصنوعی پیکربندی نشده؛ خبرها خودکار منتشر نمی‌شوند'],
        en:['News relevance','Minimum project relevance','News must meet both this threshold and the topic threshold. AI scores are computed before news selection.','Save','AI analysis is enabled','AI analysis is not configured; news will not be published automatically'],
        tr:['Haber ilgililiği','Proje için asgari ilgililik puanı','Haber hem bu eşiği hem de konu eşiğini karşılamalıdır. Yapay zekâ puanları haber seçilmeden önce hesaplanır.','Kaydet','Yapay zekâ analizi etkin','Yapay zekâ analizi yapılandırılmadı; haberler otomatik yayımlanmaz'],
        ar:['صلة الأخبار','الحد الأدنى لدرجة الصلة بالمشروع','يجب أن يبلغ الخبر هذا الحد وحد الموضوع معًا. تُحسب درجة الذكاء الاصطناعي قبل اختيار الخبر.','حفظ','تحليل الذكاء الاصطناعي مفعّل','تحليل الذكاء الاصطناعي غير مُعدّ؛ لن تُنشر الأخبار تلقائيًا'],
        de:['Nachrichtenrelevanz','Mindest­relevanz für das Projekt','Nachrichten müssen diesen und den Themen-Schwellenwert erreichen. KI-Bewertungen erfolgen vor der Auswahl.','Speichern','KI-Analyse ist aktiviert','KI-Analyse ist nicht eingerichtet; Nachrichten werden nicht automatisch veröffentlicht'],
        fr:['Pertinence des actualités','Seuil minimal du projet','Une actualité doit atteindre ce seuil et celui du sujet. Le score IA est calculé avant la sélection.','Enregistrer','Analyse IA activée','Analyse IA non configurée ; aucune publication automatique'],
        es:['Relevancia de las noticias','Relevancia mínima del proyecto','La noticia debe alcanzar este umbral y el del tema. La IA calcula la puntuación antes de seleccionar noticias.','Guardar','Análisis con IA activado','La IA no está configurada; no se publicarán noticias automáticamente'],
        it:['Pertinenza delle notizie','Pertinenza minima del progetto','Le notizie devono raggiungere questa soglia e quella dell’argomento. Il punteggio IA viene calcolato prima della selezione.','Salva','Analisi IA attiva','Analisi IA non configurata; nessuna pubblicazione automatica']
      };
      function render(){
        const root=$('view-settings');if(!root)return;
        let card=$('projectRelevanceCard');
        if(!card){
          card=document.createElement('section');card.id='projectRelevanceCard';card.className='card';card.setAttribute('data-dynamic-copy','');
          card.innerHTML='<h3 id="projectRelevanceTitle"></h3><div class="field"><div class="label-info-row"><label for="projectRelevanceThreshold" id="projectRelevanceLabel"></label><button type="button" class="info-tip" id="projectRelevanceInfo" aria-describedby="projectRelevanceHelp">i<span id="projectRelevanceHelp" class="info-tip-popup" role="tooltip"></span></button></div><input id="projectRelevanceThreshold" type="number" min="0" max="1" step="0.05" required><p id="projectAIState" class="muted"></p></div><div class="card-actions"><button id="saveProjectRelevance" type="button" class="btn primary"></button></div>';
          root.append(card);
          $('saveProjectRelevance').addEventListener('click',async()=>{
            const button=$('saveProjectRelevance'),input=$('projectRelevanceThreshold'),id=state.assistantId,value=Number(input.value);
            if(!id||!input.reportValidity())return;
            button.disabled=true;
            try{
              const result=await req('/admin/api/assistants/'+encodeURIComponent(id)+'/runtime-settings',{method:'PUT',body:JSON.stringify({relevance_threshold:value})});
              if(id===state.assistantId){state.runtimeSettings=result;render()}
              toast(localeLabel('ذخیره شد','Saved'));
            }catch(error){toast(friendlyError(error.message),true)}finally{button.disabled=false}
          });
        }
        const t=texts[state.language]||texts.en;
        $('projectRelevanceTitle').textContent=t[0];$('projectRelevanceLabel').textContent=t[1];
        $('projectRelevanceInfo').setAttribute('aria-label',t[1]);$('projectRelevanceHelp').textContent=t[2];
        if(document.activeElement!==$('projectRelevanceThreshold'))$('projectRelevanceThreshold').value=state.runtimeSettings?.relevance_threshold??state.meta?.pipeline?.relevance_threshold??0.45;
        const queueLabels={fa:'خبر در صف امتیازدهی هوش مصنوعی',en:'articles awaiting AI relevance scores',tr:'yapay zekâ ilgililik puanı bekleyen haber',ar:'أخبار تنتظر تقييم الصلة بالذكاء الاصطناعي',de:'Artikel warten auf KI-Relevanzbewertung',fr:'articles en attente du score de pertinence IA',es:'noticias pendientes de puntuación de relevancia IA',it:'notizie in attesa del punteggio di pertinenza IA'};
        $('projectAIState').textContent=t[state.runtimeSettings?.ai_analysis_ready?4:5]+(Number.isFinite(state.metrics?.pending_ai_articles)?' · '+new Intl.NumberFormat(state.language||'en').format(state.metrics.pending_ai_articles)+' '+(queueLabels[state.language]||queueLabels.en):'');
        $('saveProjectRelevance').textContent=t[3];$('saveProjectRelevance').hidden=!['admin','assistant_admin','editor','owner'].includes(state.currentUser?.role)&&!state.currentUser?.is_owner;
      }
      const baseLoad=loadAll;loadAll=async function(){await baseLoad.apply(this,arguments);render()};
      const baseLanguage=setLanguage;setLanguage=function(){const value=baseLanguage.apply(this,arguments);render();return value};window.setLanguage=setLanguage;render();
    })();
