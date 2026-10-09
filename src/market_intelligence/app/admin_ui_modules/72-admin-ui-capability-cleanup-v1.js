
    // Keep the shared action pattern and source-create action deterministic.
    // This runs after legacy UI layers so old injected controls cannot leak
    // back into the current admin surface.
    (function(){
      const doc=document;
      const normalizePageActions=()=>{
        doc.querySelectorAll('.page-head > button').forEach(button=>{
          const head=button.closest('.page-head');
          if(!head)return;
          if(button.parentElement?.classList.contains('actions'))return;
          const actions=doc.createElement('div');actions.className='actions';head.appendChild(actions);actions.appendChild(button);
        });
      };
      // Catalog-create controls use one document-level capture handler below.
      // Unlike a listener attached to the button itself, that handler survives
      // locale repaints, legacy redraws, and replacement of page-head actions.
      const actionHandlers={addPublicSocialSourceBtn:'openPublicSocialSourceModal',sourceSuggestionBtn:'openSourceSuggestionsModal',sourceProbeBtn:'probeSelectedSources'};
      const catalogHandlers={source:'openCreateSourceModal',topic:'openCreateTopicModal'};
      const ensureWorkspace=async()=>{
        // A workspace id can survive in localStorage across sign-out or an
        // account switch. Resolve it once from the data already loaded, then
        // make at most one explicit refresh.  Retrying for three seconds from
        // a click handler turned an ordinary UI action into a silent no-op.
        const resolve=()=>{
          const known=(state.assistants||[]).filter(item=>item?.id);
          const selectedId=String(doc.getElementById('workspaceSelect')?.value||'').trim();
          const current=known.find(item=>String(item.id)===String(state.assistantId));
          const candidate=current||known.find(item=>String(item.id)===selectedId)||known[0];
          if(!candidate?.id)return false;
          state.assistantId=candidate.id;
          localStorage.setItem('research_bee_workspace',candidate.id);
          return true
        };
        if(resolve())return true;
        if(typeof window.loadAll==='function'){
          try{await window.loadAll()}catch(_){return false}
        }
        return resolve()
      };
      const invokeAction=async(button,fnName,event)=>{
        if(button.dataset.adminActionBusy==='1')return;
        button.dataset.adminActionBusy='1';button.disabled=true;button.setAttribute('aria-busy','true');
        try{
          if(!(await ensureWorkspace())){toast(state.language==='en'?'Select an authorized assistant first.':'ابتدا یک دستیار مجاز انتخاب کنین.',true);return}
          const fn=window[fnName];if(typeof fn!=='function'){toast(state.language==='en'?'This action is temporarily unavailable.':'این عملیات موقتاً در دسترس نیست.',true);return}
          await fn.call(button,event)
        }catch(error){
          // An action used to fail silently here because this async handler is
          // deliberately fire-and-forget.  Keep the page interactive and give
          // the operator a localized, actionable error instead of a button
          // that appears to have done nothing.
          const detail=typeof window.friendlyError==='function'?window.friendlyError(error?.message||String(error||'')):(state.language==='en'?'The action could not be opened. Please try again.':'عملیات باز نشد؛ دوباره تلاش کنین.');
          toast(detail|| (state.language==='en'?'The action could not be opened. Please try again.':'عملیات باز نشد؛ دوباره تلاش کنین.'),true);
          // Report only the coarse active view. Never transmit exception
          // text, form values, URLs, or customer data.
          try{reportOverviewClientError('window')}catch(_){}
        }finally{button.disabled=false;button.dataset.adminActionBusy='0';button.removeAttribute('aria-busy')}
      };
      const prepareActionButtons=()=>Object.entries(actionHandlers).forEach(([id,fnName])=>{
        const button=doc.getElementById(id);if(!button)return;button.type='button';
        // Legacy renderers may assign an onclick property after a redraw.
        // Reconciliation always removes it, leaving exactly one event path.
        button.onclick=null;
        if(button.dataset.adminActionBound==='1')return;
        button.dataset.adminActionBound='1';
        // Bind once on the control itself. The explicit reconciliation above
        // clears later legacy assignments without a document-wide observer.
        button.addEventListener('click',event=>{
          event.preventDefault();
          void invokeAction(button,fnName,event)
        })
      });
      const prepareCatalogButtons=()=>{
        [['addSourceBtn','source'],['addTopicBtn','topic']].forEach(([id,kind])=>{
          const button=doc.getElementById(id);if(!button)return;
          button.type='button';button.dataset.catalogCreate=kind;
          // Remove every property handler installed by older render layers.
          // The stable capture listener below is the only catalog-create path.
          button.onclick=null;button.disabled=false;button.removeAttribute('aria-busy');
          delete button.dataset.adminActionBound;delete button.dataset.adminActionBusy
        })
      };
      const resolveCatalogWorkspace=()=>{
        const known=(state.assistants||[]).filter(item=>item?.id);
        const selectedId=String(doc.getElementById('workspaceSelect')?.value||'').trim();
        const candidate=known.find(item=>String(item.id)===selectedId)||known.find(item=>String(item.id)===String(state.assistantId))||known[0];
        const assistantId=String(candidate?.id||selectedId||'').trim();
        if(!assistantId)return false;
        state.assistantId=assistantId;localStorage.setItem('research_bee_workspace',assistantId);return true
      };
      // Workspace-dependent controls used to return early when the first
      // render exposed a button before /admin/api/assistants had finished.
      // Gate those controls once, reload the authorized workspace if needed,
      // then replay the original click.  This keeps every action deterministic
      // instead of making a button appear inert during the initial paint.
      const workspaceGateIds=new Set(['addSourceBtn','addTopicBtn','sourceProbeBtn','healthProbeBtn','runPipelineBtn','operationsRunBtn','saveScheduleBtn','saveLimitsBtn','saveCollectionSettingsBtn','feedbackReportBtn','feedbackLearningBtn','feedbackRollbackBtn','knowledgeEditBtn','privacySaveBtn','privacyExportBtn','templateBuilderBtn']);
      const safeActionRoute=route=>String(route||'unknown').split('?')[0].replace(/\/[0-9a-f]{8,}(?:-[0-9a-f]{4,}){1,4}(?=\/|$)/gi,'/:id').replace(/\/\d+(?=\/|$)/g,'/:id').replace(/[^A-Za-z0-9_.:/-]/g,'').slice(0,96)||'unknown';
      const actionTrace=(action,phase,outcome,details={})=>{try{const actionName=String(action||'unknown'),phaseName=String(phase||'unknown'),result=String(outcome||'ok'),view=doc.querySelector('.view.active')?.id?.replace(/^view-/,'')||'unknown',trace=Array.isArray(window.__researchBeeActionTrace)?window.__researchBeeActionTrace:[],entry={action:actionName,phase:phaseName,outcome:result,at:Date.now(),view};if(details.route)entry.route=safeActionRoute(details.route);if(Number.isFinite(Number(details.status)))entry.status=Number(details.status);if(Number.isFinite(Number(details.duration)))entry.duration_ms=Number(details.duration);trace.push(entry);while(trace.length>50)trace.shift();window.__researchBeeActionTrace=trace;if(result==='waiting'&&phaseName==='click'){const context={action:actionName,startedAt:Date.now()};window.__researchBeeActionContext=context;setTimeout(()=>{if(window.__researchBeeActionContext===context){actionTrace(actionName,'timeout','error',{route:'client',duration:Date.now()-context.startedAt})}},3200)}if(result==='error'||phaseName==='modal')window.__researchBeeActionContext=null;if(result==='error')reportOverviewClientError('action',{action:actionName,phase:phaseName,outcome:result,route:details.route||'client',status:details.status||0,duration:details.duration||0})}catch(_){}};
      window.__researchBeeTraceRequest=(url,method,status,duration,outcome)=>{const context=window.__researchBeeActionContext;if(!context||Date.now()-context.startedAt>30000)return;const failed=outcome!=='response'||Number(status)>=400;actionTrace(context.action,'request',failed?'error':'ok',{route:url,status:Number(status)||0,duration:Number(duration)||0})};
      const workspaceReady=()=>{const selected=String(state.assistantId||'').trim(),known=(state.assistants||[]).some(item=>String(item?.id||'')===selected);return Boolean(selected&&known)};
      const handleWorkspaceGate=event=>{
        const origin=event.target instanceof Element?event.target:event.target?.parentElement;
        const button=origin?.closest?.('button');
        if(!button||!doc.contains(button)||!workspaceGateIds.has(button.id)||workspaceReady())return;
        if(button.dataset.workspaceReplay==='1'){delete button.dataset.workspaceReplay;return}
        event.preventDefault();event.stopImmediatePropagation();
        if(button.dataset.workspaceGateBusy==='1')return;
        actionTrace(button.id,'click','waiting');
        button.dataset.workspaceGateBusy='1';button.disabled=true;button.setAttribute('aria-busy','true');
        void ensureWorkspace().then(ready=>{
          if(!ready){actionTrace(button.id,'workspace','error');toast(state.language==='en'?'Select an authorized assistant first.':'ابتدا یک دستیار مجاز انتخاب کنین.',true);return}
          // loadAll may replace page-head controls while the workspace is being
          // resolved. Always replay on the live DOM node, never on a detached
          // reference captured before the asynchronous refresh.
          const replay=doc.getElementById(button.id);
          if(!replay){actionTrace(button.id,'replay_target','error');throw Error('workspace_action_target_missing')}
          replay.dataset.workspaceReplay='1';replay.disabled=false;replay.removeAttribute('aria-busy');actionTrace(button.id,'replay','ok');replay.click();
        }).catch(error=>{const detail=typeof window.friendlyError==='function'?window.friendlyError(error?.message||String(error||'')):String(error?.message||error||'');actionTrace(button.id,'workspace','error');toast(detail||(state.language==='en'?'The selected assistant could not be loaded. Please try again.':'دستیار انتخاب‌شده بارگذاری نشد؛ دوباره تلاش کنین.'),true)}).finally(()=>{button.disabled=false;button.dataset.workspaceGateBusy='0';button.removeAttribute('aria-busy')})
      };
      doc.addEventListener('click',handleWorkspaceGate,true);
      const handleCatalogCreate=async event=>{
        const origin=event.target instanceof Element?event.target:event.target?.parentElement;
        const button=origin?.closest?.('[data-catalog-create]');
        if(!button||!doc.contains(button))return;
        // Run before target/bubble listeners so obsolete handlers cannot
        // cancel, duplicate, or silently swallow this interaction.
        event.preventDefault();event.stopImmediatePropagation();
        if(button.dataset.catalogCreateBusy==='1')return;
        actionTrace('catalog_'+button.dataset.catalogCreate,'click','waiting');
        button.dataset.catalogCreateBusy='1';
        try{
          if(!(await ensureWorkspace())){
            actionTrace('catalog_'+button.dataset.catalogCreate,'workspace','error');toast(state.language==='en'?'Select an authorized assistant first.':'ابتدا یک دستیار مجاز انتخاب کنین.',true);return
          }
          if(!resolveCatalogWorkspace())throw Error(state.language==='en'?'Select an authorized assistant first.':'ابتدا یک دستیار مجاز انتخاب کنین.');
          const fnName=catalogHandlers[button.dataset.catalogCreate],fn=window[fnName];
          if(typeof fn!=='function')throw Error(state.language==='en'?'This action is temporarily unavailable.':'این عملیات موقتاً در دسترس نیست.');
          await Promise.resolve(fn.call(button,event));
          const modalRoot=doc.getElementById('modalRoot');
          if(!modalRoot||modalRoot.classList.contains('hidden'))throw Error(state.language==='en'?'The form could not be opened. Please try again.':'فرم باز نشد؛ دوباره تلاش کنین.')
          actionTrace('catalog_'+button.dataset.catalogCreate,'modal','ok');
        }catch(error){
          const detail=typeof window.friendlyError==='function'?window.friendlyError(error?.message||String(error||'')):String(error?.message||error||'');
          toast(detail||(state.language==='en'?'The form could not be opened. Please try again.':'فرم باز نشد؛ دوباره تلاش کنین.'),true);
          actionTrace('catalog_'+button.dataset.catalogCreate,'handler','error');
        }finally{button.dataset.catalogCreateBusy='0'}
      };
      doc.addEventListener('click',handleCatalogCreate,true);
      const run=()=>{normalizePageActions();prepareCatalogButtons();prepareActionButtons()};
      run();
      // Workspace renderers call ensureWorkspaceActions after replacing rows
      // or page actions.  Observing every DOM insertion here made a normal
      // table refresh repeatedly reconcile the full document and was a
      // measurable source of slow pages.  Keep one explicit reconciliation
      // hook for those renderers instead of a global observer.
      window.__researchBeeReconcileWorkspaceActions=run;
      window.__researchBeeAdminCapabilityCleanup={run,invokeAction,handleCatalogCreate};
    })();
