
    /* A single final owner-facing media workflow.  Earlier releases kept a
       direct form and a catalog wizard in parallel, which made the required
       review-first journey hard to reason about.  The endpoints remain
       scoped; this layer only chooses their deliberate UI sequence. */
    (function(){
      const copy=()=>{
        const en=state.language==='en';
        return en?{
          health:'Check media health',discover:'Suggest media',add:'Add media',
          addTitle:'Add media',addIntro:'Enter a media name and an optional research angle. We will identify public connection details, test that the content can be read, then let you review them before anything is added.',
          name:'Media name',nameHint:'For example: TechCrunch, Reuters, or a public Telegram channel',angle:'Research angle (optional)',angleHint:'What should make this source useful for this assistant?',review:'Review media',reviewing:'Researching and testing the media…',
          resultTitle:'Media review',ready:'Ready to add',notFound:'No usable media found',notUsable:'Media could not be read',needsReview:'Connection needs review',
          verified:'The connection and sample content were verified. Review the editable details, then confirm.',
          alternative:'Did you mean one of these?',tryAlternative:'Review this name',
          homepage:'Homepage URL',feed:'Feed / fetch URL',adapter:'Connection type',priority:'Priority',outputLanguage:'Publication language',sourceLanguage:'Source language',notes:'Access notes',fit:'Why it fits this assistant',
          save:'Add media',saving:'Adding media…',saved:'Media was added and its first health check completed.',
          manualSave:'Review and add',manualIntro:'Automatic verification is unavailable or incomplete. Check the details, correct the feed if needed, and add it only when you are satisfied.',
          retry:'Try another name',done:'Done',cancel:'Cancel',
          healthTitle:'Media health check',healthIntro:'Each active source was checked with the same connector and parser used by collection. No content was published.',
          media:'Media',healthy:'Healthy',degraded:'Needs attention',failed:'Unavailable',checked:'Checked',items:'readable items',
          none:'There are no active media sources to check.',
          suggestTitle:'Suggest media',suggestIntro:'Search worldwide for up to 10 public media sources. Review each suggestion before adding it; refresh to search for different publishers.',
          keyword:'Keyword',keywordHint:'For example: embedded finance, AI policy, retail banking',search:'Find media',searching:'Searching…',suggested:'Media suggestions are ready below the list.',noSuggestions:'No suitable media was identified for this search.',
          required:'Enter a media name first.',keywordRequired:'Enter a keyword first.'
        }:{
          health:'بررسی سلامت رسانه‌ها',discover:'پیشنهاد رسانه',add:'افزودن رسانه',
          addTitle:'افزودن رسانه',addIntro:'نام رسانه و در صورت نیاز زاویهٔ بررسی را وارد کنین. ابتدا اطلاعات اتصال عمومی شناسایی و خوانایی محتوا آزمایش می‌شود؛ سپس قبل از ثبت نهایی همه‌چیز قابل مرور و ویرایش است.',
          name:'نام رسانه',nameHint:'مثلاً TechCrunch، رویترز یا یک کانال عمومی تلگرام',angle:'توضیح یا زاویهٔ بررسی (اختیاری)',angleHint:'این رسانه چرا باید برای این دستیار مفید باشد؟',review:'بررسی رسانه',reviewing:'در حال تحقیق و آزمایش رسانه…',
          resultTitle:'نتیجه بررسی رسانه',ready:'آماده ثبت',notFound:'رسانهٔ قابل استفاده پیدا نشد',notUsable:'خواندن رسانه تأیید نشد',needsReview:'نیازمند مرور اتصال',
          verified:'اتصال و خواندن نمونه‌ای از محتوا تأیید شد. جزئیات را مرور کنین و سپس ثبت نهایی را بزنین.',
          alternative:'ممکن است منظورتان یکی از این‌ها باشد؟',tryAlternative:'بررسی این نام',
          homepage:'آدرس صفحه اصلی',feed:'ورودی دریافت / فید',adapter:'نوع اتصال',priority:'اولویت',outputLanguage:'زبان انتشار',sourceLanguage:'زبان اصلی رسانه',notes:'یادداشت دسترسی',fit:'دلیل تناسب با این دستیار',
          save:'ثبت رسانه',saving:'در حال ثبت رسانه…',saved:'رسانه ثبت شد و نخستین بررسی سلامت آن انجام شد.',
          manualSave:'مرور و ثبت رسانه',manualIntro:'بررسی خودکار کامل نشد یا موقتاً در دسترس نبود. جزئیات را مرور و در صورت نیاز ورودی رسانه را اصلاح کنین؛ فقط پس از تأیید شما ثبت می‌شود.',
          retry:'نام دیگری را بررسی کنین',done:'بستن',cancel:'انصراف',
          healthTitle:'نتیجه سلامت رسانه‌ها',healthIntro:'هر رسانهٔ فعال با همان اتصال و parser مورد استفاده در خزش بررسی شد. در این عملیات هیچ محتوایی منتشر نمی‌شود.',
          media:'رسانه',healthy:'سالم',degraded:'نیازمند بررسی',failed:'در دسترس نیست',checked:'بررسی‌شده',items:'مورد قابل‌خواندن',
          none:'رسانهٔ فعالی برای بررسی وجود ندارد.',
          suggestTitle:'پیشنهاد رسانه',suggestIntro:'تا ۱۰ رسانهٔ عمومی از سراسر جهان جست‌وجو می‌شود. قبل از افزودن هر پیشنهاد آن را مرور کنید؛ برای رسانه‌های متفاوت بازخوانی کنید.',
          keyword:'کلیدواژه',keywordHint:'مثلاً بانکداری باز، هوش مصنوعی یا فین‌تک',search:'پیشنهاد رسانه',searching:'در حال جست‌وجو…',suggested:'پیشنهادهای رسانه زیر فهرست نمایش داده شدند.',noSuggestions:'برای این جست‌وجو رسانهٔ مناسب و قابل اتکایی پیدا نشد.',
          required:'ابتدا نام رسانه را وارد کنین.',keywordRequired:'ابتدا کلیدواژه را وارد کنین.'
        }
      };
      const ensureAssistant=()=>{
        if(state.assistantId)return true;
        toast(state.language==='en'?'Select an authorized assistant first.':'ابتدا یک دستیار مجاز انتخاب کنین.',true);
        return false;
      };
      const languageOptions=(selected='source',en=state.language==='en')=>[
        ['source',en?'Follow source / business language':'زبان اصلی رسانه / بیزینس'],
        ['fa','فارسی'],['en','English'],['tr','Türkçe'],['ar','العربية'],['it','Italiano'],['es','Español'],['de','Deutsch'],['fr','Français']
      ].map(([value,label])=>`<option value="${value}" ${String(selected||'source')===value?'selected':''}>${label}</option>`).join('');
      const providerProblem=(code)=>{const labels={fa:['اعتبار حساب API هوش مصنوعی تمام شده است. مالک باید حساب API را شارژ کند؛ این اعتبار جدا از Codex است.','سرویس AI در دسترس نیست؛ این به معنی نبود رسانه نیست. می‌توانید آدرس عمومی رسانه را دستی وارد کنید.'],en:['The AI API account has no credits. The owner must fund the API account; this is separate from Codex.','AI is unavailable; this does not mean no media exists. You can enter a public media URL manually.'],tr:['AI API hesabının kredisi bitti. Hesap sahibi API hesabına kredi eklemelidir; Codex kredisi ayrıdır.','AI kullanılamıyor; bu, medya olmadığı anlamına gelmez. Genel medya URL’sini elle girebilirsiniz.'],ar:['نفد رصيد حساب API للذكاء الاصطناعي. يجب على المالك شحن الحساب؛ رصيد Codex منفصل.','خدمة الذكاء الاصطناعي غير متاحة؛ هذا لا يعني عدم وجود مصدر. يمكن إدخال رابط عام يدويًا.'],es:['La cuenta de API de IA no tiene saldo. El propietario debe recargarla; el saldo de Codex es independiente.','La IA no está disponible; no significa que no existan medios. Puede introducir una URL pública manualmente.'],it:['Il credito dell’account API IA è esaurito. Il proprietario deve ricaricarlo; il credito Codex è separato.','L’IA non è disponibile; non significa che non esistano fonti. È possibile inserire un URL pubblico manualmente.'],de:['Das KI-API-Guthaben ist aufgebraucht. Der Eigentümer muss das API-Konto aufladen; Codex-Guthaben ist getrennt.','KI ist nicht verfügbar; das bedeutet nicht, dass keine Quelle existiert. Eine öffentliche Medien-URL kann manuell eingegeben werden.'],fr:['Le crédit du compte API IA est épuisé. Le propriétaire doit le recharger ; le crédit Codex est distinct.','L’IA est indisponible ; cela ne signifie pas qu’aucun média n’existe. Vous pouvez saisir une URL publique manuellement.']};if(!code||code==='succeeded')return '';return (labels[state.language]||labels.en)[code==='provider_quota_exhausted'?0:1]};
      const resultStatus=(value,c)=>value==='provider_unavailable'?`<span class="status draft">AI</span>`:value==='ready'?`<span class="status active">${c.ready}</span>`:`<span class="status ${value==='not_found'||value==='needs_review'?'draft':'failed'}">${value==='not_found'?c.notFound:value==='needs_review'?c.needsReview:c.notUsable}</span>`;
      const openAddMedia=(suggestedName='')=>{
        if(!ensureAssistant())return;
        const c=copy();
        modal(c.addTitle,`<div class="notice">${c.addIntro}</div><div class="form-grid"><div class="field full"><label for="mediaDraftName">${c.name}</label><input id="mediaDraftName" maxlength="160" autocomplete="off" placeholder="${c.nameHint}" value="${esc(suggestedName)}"></div><div class="field full"><label for="mediaDraftInstruction">${c.angle}</label><textarea id="mediaDraftInstruction" maxlength="4000" placeholder="${c.angleHint}"></textarea></div></div>`,async()=>{
          const name=$('mediaDraftName')?.value.trim();
          if(!name){toast(c.required,true);$('mediaDraftName')?.focus();return}
          const submit=$('modalSubmit');submit.disabled=true;submit.textContent=c.reviewing;
          try{
            const assistantId=state.assistantId;
            const response=await req('/admin/api/assistants/'+encodeURIComponent(assistantId)+'/sources/draft',{method:'POST',timeoutMs:150000,body:JSON.stringify({name,instruction:$('mediaDraftInstruction')?.value.trim()||''})});
            if(assistantId!==state.assistantId){closeModal();return}
            response.assistantId=assistantId;
            openMediaDraftReview(response,name);
          }catch(error){submit.disabled=false;submit.textContent=c.review;toast(friendlyError(error.message),true)}
        },c.review);
      };
      const openMediaDraftManual=(draft,requestedName,verification={})=>{
        const c=copy(),adapter=String(draft?.adapter||'rss');
        modal(c.resultTitle,`<div class="media-discovery-result"><div class="notice warn">${resultStatus(String(verification.status||'needs_review'),c)}<p>${esc(providerProblem(verification.provider_status)||verification.message||c.manualIntro)}</p></div><div class="notice">${c.manualIntro}</div><div class="form-grid"><div class="field full"><label>${c.name}</label><input id="mediaManualName" maxlength="160" value="${esc(draft?.name||requestedName||'')}"></div><div class="field"><label>${c.homepage}</label><input id="mediaManualHomepage" type="url" maxlength="2048" value="${esc(draft?.homepage_url||'')}"></div><div class="field"><label>${c.feed}</label><input id="mediaManualFeed" type="url" maxlength="2048" value="${esc(draft?.fetch_url||'')}"></div><div class="field"><label>${c.adapter}</label><select id="mediaManualAdapter"><option value="rss" ${adapter==='rss'?'selected':''}>RSS</option><option value="html" ${adapter==='html'?'selected':''}>HTML</option><option value="json" ${adapter==='json'?'selected':''}>JSON</option><option value="telegram_public" ${adapter==='telegram_public'?'selected':''}>Telegram public</option></select></div><div class="field"><label>${c.sourceLanguage}</label><input id="mediaManualSourceLanguage" maxlength="16" value="${esc(draft?.language||'unknown')}"></div><div class="field"><label>${c.outputLanguage}</label><select id="mediaManualOutputLanguage">${languageOptions(draft?.output_language||'source')}</select></div><div class="field"><label>${c.priority}</label><input id="mediaManualPriority" type="number" min="1" max="5" value="${esc(String(draft?.priority||3))}"></div><div class="field full"><label>${c.notes}</label><textarea id="mediaManualNotes" maxlength="4000">${esc(draft?.access_notes||'')}</textarea></div></div></div>`,async()=>{
          const submit=$('modalSubmit');submit.disabled=true;submit.textContent=c.saving;
          try{
            const created=await req('/admin/api/assistants/'+encodeURIComponent(state.assistantId)+'/sources',{method:'POST',body:JSON.stringify({name:$('mediaManualName').value.trim(),homepage_url:$('mediaManualHomepage').value.trim(),fetch_url:$('mediaManualFeed').value.trim(),adapter:$('mediaManualAdapter').value,language:$('mediaManualSourceLanguage').value.trim()||'unknown',output_language:$('mediaManualOutputLanguage').value,priority:Number($('mediaManualPriority').value||3),access_notes:$('mediaManualNotes').value.trim()||null})});
            closeModal();await loadAll();toast(c.saved);try{await req('/admin/api/assistants/'+encodeURIComponent(state.assistantId)+'/sources/'+encodeURIComponent(created.id)+'/probe',{method:'POST'})}catch(_){/* health can be retried from the page */}
          }catch(error){submit.disabled=false;submit.textContent=c.manualSave;toast(friendlyError(error.message),true)}
        },c.manualSave);
      };
      const openMediaDraftReview=(response,requestedName)=>{
        const c=copy(),draft=response?.draft||{},verification=response?.verification||{},status=String(verification.status||'not_usable');
        const alternatives=(Array.isArray(draft.alternatives)?draft.alternatives:[]).map(value=>String(value).trim()).filter(Boolean).slice(0,3);
        if(status!=='ready'){
          modal(c.resultTitle,`<div class="media-discovery-result"><div class="notice warn">${resultStatus(status,c)}<p>${esc(providerProblem(verification.provider_status||draft.provider_status)||verification.message||draft.match_explanation||c.noSuggestions)}</p></div>${alternatives.length?`<div class="detail-list"><div class="detail-item"><span>${c.alternative}</span><div class="media-alternatives">${alternatives.map(value=>`<button type="button" class="btn small" data-media-alternative="${esc(value)}">${esc(value)}</button>`).join('')}</div></div></div>`:''}<div class="card-actions"><button type="button" class="btn primary" id="mediaManualReview">${c.manualSave}</button></div></div>`,()=>{closeModal();openAddMedia(requestedName)},c.retry);
          $('mediaManualReview')?.addEventListener('click',()=>{closeModal();openMediaDraftManual(draft,requestedName,verification)});
          document.querySelectorAll('[data-media-alternative]').forEach(button=>button.addEventListener('click',()=>{const value=button.dataset.mediaAlternative||'';closeModal();openAddMedia(value)}));
          return;
        }
        const adapter=String(draft.adapter||'rss');
        modal(c.resultTitle,`<div class="media-discovery-result"><div class="notice success">${resultStatus('ready',c)}<p>${esc(verification.message||c.verified)}${Number(verification.items_found||0)?` · ${esc(String(verification.items_found))} ${c.items}`:''}</p></div><div class="form-grid"><div class="field full"><label>${c.name}</label><input id="mediaReviewName" maxlength="160" value="${esc(draft.name||requestedName)}"></div><div class="field"><label>${c.homepage}</label><input id="mediaReviewHomepage" type="url" maxlength="2048" value="${esc(draft.homepage_url||'')}"></div><div class="field"><label>${c.feed}</label><input id="mediaReviewFeed" type="url" maxlength="2048" value="${esc(draft.fetch_url||'')}"></div><div class="field"><label>${c.adapter}</label><select id="mediaReviewAdapter"><option value="rss" ${adapter==='rss'?'selected':''}>RSS</option><option value="html" ${adapter==='html'?'selected':''}>HTML</option><option value="json" ${adapter==='json'?'selected':''}>JSON</option><option value="telegram_public" ${adapter==='telegram_public'?'selected':''}>Telegram public</option></select></div><div class="field"><label>${c.sourceLanguage}</label><input id="mediaReviewSourceLanguage" maxlength="16" value="${esc(draft.language||'unknown')}"></div><div class="field"><label>${c.priority}</label><input id="mediaReviewPriority" type="number" min="1" max="5" value="${esc(String(draft.priority||3))}"></div><div class="field"><label>${c.outputLanguage}</label><select id="mediaReviewOutputLanguage">${languageOptions(draft.output_language||'source')}</select></div><div class="field full"><label>${c.notes}</label><textarea id="mediaReviewNotes" maxlength="4000">${esc(draft.access_notes||'')}</textarea></div>${draft.fit_reason?`<div class="field full"><label>${c.fit}</label><div class="notice">${esc(draft.fit_reason)}</div></div>`:''}</div></div>`,async()=>{
          const submit=$('modalSubmit');submit.disabled=true;submit.textContent=c.saving;
          try{
            const created=await req('/admin/api/assistants/'+encodeURIComponent(state.assistantId)+'/sources',{method:'POST',body:JSON.stringify({name:$('mediaReviewName').value.trim(),homepage_url:$('mediaReviewHomepage').value.trim(),fetch_url:$('mediaReviewFeed').value.trim(),adapter:$('mediaReviewAdapter').value,language:$('mediaReviewSourceLanguage').value.trim()||'unknown',output_language:$('mediaReviewOutputLanguage').value,priority:Number($('mediaReviewPriority').value||3),access_notes:$('mediaReviewNotes').value.trim()||null})});
            closeModal();await loadAll();
            try{const probe=await req('/admin/api/assistants/'+encodeURIComponent(state.assistantId)+'/sources/'+encodeURIComponent(created.id)+'/probe',{method:'POST'});toast(probe.status==='completed'?c.saved:(state.language==='en'?'Media was added, but its first health check needs attention.':'رسانه ثبت شد، اما نخستین بررسی سلامت آن نیازمند رسیدگی است.'),probe.status!=='completed')}catch(_){toast(state.language==='en'?'Media was added. Run Media health to confirm it.':'رسانه ثبت شد. برای تأیید اتصال، بررسی سلامت رسانه‌ها را اجرا کنین.')}
          }catch(error){submit.disabled=false;submit.textContent=c.save;toast(friendlyError(error.message),true)}
        },c.save);
      };
      loadSourceSuggestions=async function(){
        const id=state.assistantId,root=$('sourceSuggestionsRows'),card=$('sourceSuggestionsCard');if(!id||!root||!card)return;
        try{const payload=await req('/admin/api/assistants/'+encodeURIComponent(id)+'/source-suggestions');if(id!==state.assistantId)return;const rows=payload.suggestions||[];card.classList.toggle('hidden',!rows.length&&state.mediaDiscovery?.assistantId!==id);root.innerHTML=rows.map(row=>{const d=row.draft||{},links=(d.evidence||[]).filter(url=>/^https?:\/\//i.test(url)).slice(0,3);return `<article class="channel-card"><div class="channel-card-head"><div><b>${esc(d.name||row.name)}</b><span class="muted">${esc(d.summary||'')}</span></div><span class="status draft">${esc(localeLabel('در انتظار تأیید مالک','Pending owner approval'))}</span></div><p>${esc(d.fit_reason||'')}</p><div class="muted">${esc([d.region,d.language].filter(Boolean).join(' · '))}</div><div class="media-evidence">${links.map(url=>`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" data-latin="true">${esc(url)}</a>`).join('<br>')}</div>${payload.can_approve?`<div class="card-actions"><button type="button" class="btn small danger" data-media-reject="${esc(row.id)}">${esc(localeLabel('رد','Reject'))}</button><button type="button" class="btn small primary" data-media-approve="${esc(row.id)}">${esc(localeLabel('تأیید و بررسی اتصال','Approve and check connection'))}</button></div>`:''}</article>`}).join('');root.querySelectorAll('[data-media-approve],[data-media-reject]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{const approve=Boolean(button.dataset.mediaApprove),suggestion=button.dataset.mediaApprove||button.dataset.mediaReject;await req('/admin/api/assistants/'+encodeURIComponent(id)+'/source-suggestions/'+encodeURIComponent(suggestion)+'/'+(approve?'approve':'reject'),{method:'POST',timeoutMs:120000});if(id===state.assistantId){await loadAll();await loadSourceSuggestions()}}catch(error){button.disabled=false;toast(friendlyError(error.message),true)}}));synchronize()}catch(error){toast(friendlyError(error.message),true)}
      };
      const openSuggestions=()=>{
        if(!ensureAssistant())return;
        const c=copy();
        modal(c.suggestTitle,`<div class="notice">${c.suggestIntro}</div><div class="form-grid"><div class="field full"><label>${c.keyword}</label><input id="mediaSuggestKeyword" maxlength="240" autocomplete="off" placeholder="${c.keywordHint}"></div><div class="field full"><label>${c.angle}</label><textarea id="mediaSuggestInstruction" maxlength="4000" placeholder="${c.angleHint}"></textarea></div></div>`,async()=>{
          const keyword=$('mediaSuggestKeyword')?.value.trim();if(!keyword){toast(c.keywordRequired,true);$('mediaSuggestKeyword')?.focus();return}
          const submit=$('modalSubmit');submit.disabled=true;submit.textContent=c.searching;
          try{
            const assistantId=state.assistantId,instruction=$('mediaSuggestInstruction')?.value.trim()||'';
            const response=await req('/admin/api/assistants/'+encodeURIComponent(assistantId)+'/source-suggestions',{method:'POST',timeoutMs:110000,body:JSON.stringify({name:keyword,instruction})});
            if(assistantId!==state.assistantId){closeModal();return}
            state.mediaDiscovery={assistantId,name:keyword,instruction,page:0,provider:response.provider,providerStatus:response.provider_status};
            closeModal();await loadSourceSuggestions();
            if(Number(response.count||0)>0){toast(c.suggested);return}
            const alternatives=(response.alternatives||[]).map(value=>String(value).trim()).filter(Boolean).slice(0,3);
            modal(c.suggestTitle,`<div class="media-discovery-result"><div class="notice warn">${esc(providerProblem(response.provider_status)||response.message||c.noSuggestions)}</div>${alternatives.length?`<div class="detail-list"><div class="detail-item"><span>${c.alternative}</span><div class="media-alternatives">${alternatives.map(value=>`<button type="button" class="btn small" data-media-alternative="${esc(value)}">${esc(value)}</button>`).join('')}</div></div></div>`:''}</div>`,()=>closeModal(),c.done);
            document.querySelectorAll('[data-media-alternative]').forEach(button=>button.addEventListener('click',()=>{const value=button.dataset.mediaAlternative||'';closeModal();openAddMedia(value)}));
          }catch(error){submit.disabled=false;submit.textContent=c.search;toast(friendlyError(error.message),true)}
        },c.search);
      };
      const probeAll=async()=>{
        if(!ensureAssistant())return;
        const c=copy();toast(state.language==='en'?'Checking media health…':'بررسی سلامت رسانه‌ها در حال انجام است…');
        try{
          const result=await req('/sources/health-probe?assistant_id='+encodeURIComponent(state.assistantId),{method:'POST'});await loadAll();
          const rows=Array.isArray(result.results)?result.results:[];
          const summary=[['healthy',result.healthy||0,c.healthy],['degraded',result.degraded||0,c.degraded],['failed',result.failed||0,c.failed]].map(([kind,count,label])=>`<div class="detail-item"><span>${label}</span><b class="status ${kind==='healthy'?'active':kind==='degraded'?'draft':'failed'}">${esc(String(count))}</b></div>`).join('');
          modal(c.healthTitle,`<div class="media-discovery-result"><div class="notice">${c.healthIntro}</div>${rows.length?`<div class="media-health-summary">${summary}</div><div>${rows.map(row=>{const kind=row.status==='succeeded'||row.status==='not_modified'?'healthy':row.status==='degraded'?'degraded':'failed';return `<div class="media-health-row"><div><b>${esc(row.source_key||c.media)}</b><small>${esc(row.error||`${Number(row.items_seen||0)} ${c.items}`)}</small></div><span class="status ${kind==='healthy'?'active':kind==='degraded'?'draft':'failed'}">${kind==='healthy'?c.healthy:kind==='degraded'?c.degraded:c.failed}</span></div>`}).join('')}</div>`:`<div class="empty">${c.none}</div>`}</div>`,()=>closeModal(),c.done);
        }catch(error){toast(friendlyError(error.message),true)}
      };
      window.openCreateSourceModal=function(eventOrName){openAddMedia(typeof eventOrName==='string'?eventOrName:'')};
      window.openSourceSuggestionsModal=openSuggestions;
      window.probeSelectedSources=probeAll;
      const synchronize=()=>{
        const c=copy(),probe=$('sourceProbeBtn'),suggest=$('sourceSuggestionBtn'),add=$('addSourceBtn');
        if(probe)probe.textContent=c.health;
        if(suggest)suggest.textContent=c.discover;
        if(add)add.textContent='＋ '+c.add;
        const card=$('sourceSuggestionsCard');
        let refresh=$('refreshMediaDiscovery');
        if(card&&!refresh){refresh=document.createElement('button');refresh.id='refreshMediaDiscovery';refresh.type='button';refresh.className='btn small';card.prepend(refresh);refresh.addEventListener('click',async()=>{const search=state.mediaDiscovery;if(!search||search.assistantId!==state.assistantId)return;refresh.disabled=true;try{const page=Math.min(search.page+1,9);const response=await req('/admin/api/assistants/'+encodeURIComponent(search.assistantId)+'/source-suggestions',{method:'POST',timeoutMs:110000,body:JSON.stringify({...search,page})});if(search.assistantId!==state.assistantId)return;search.page=page;await loadSourceSuggestions();if(!response.count)toast(localeLabel('نتیجهٔ جدیدی پیدا نشد؛ کلیدواژه را دقیق‌تر کنید.','No new results; refine the keyword.'))}catch(error){toast(friendlyError(error.message),true)}finally{refresh.disabled=false}})}
        if(refresh){refresh.textContent=localeLabel('جست‌وجوی رسانه‌های جدید','Find different media');refresh.hidden=!state.mediaDiscovery||state.mediaDiscovery.assistantId!==state.assistantId}
        let provider=$('mediaDiscoveryProvider');
        if(card&&!provider){provider=document.createElement('p');provider.id='mediaDiscoveryProvider';provider.className='muted';provider.setAttribute('data-dynamic-copy','');card.prepend(provider)}
        if(provider){const search=state.mediaDiscovery,labels={fa:'موتور جست‌وجو',en:'Search provider',tr:'Arama sağlayıcısı',ar:'مزود البحث',de:'Suchanbieter',fr:'Moteur de recherche',es:'Proveedor de búsqueda',it:'Motore di ricerca'};provider.hidden=!search||search.assistantId!==state.assistantId;provider.textContent=(labels[state.language]||labels.en)+': '+(search?.provider==='google'?'Google':search?.provider==='openai_web_search'?'OpenAI web search':localeLabel('فهرست محلی؛ جست‌وجوی زنده در دسترس نیست','Local directory; live search unavailable'))}
      };
      synchronize();
      const originalLanguage=window.setLanguage;
      if(typeof originalLanguage==='function')window.setLanguage=function(language){const result=originalLanguage(language);synchronize();return result};
      document.addEventListener('change',()=>requestAnimationFrame(synchronize),true);
    })();
