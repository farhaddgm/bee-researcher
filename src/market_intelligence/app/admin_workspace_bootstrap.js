/* Canonical authorized workspace bootstrap; included synchronously in the core asset. */
async function loadAll(){
      const actor=String(state.currentUser?.id||''),requested=state.assistantId;
      if(!actor)return;
      const sameActor=()=>actor===String(state.currentUser?.id||'');
      const scopeResult=()=>({__beeLifecycleScope:actor+':'+String(state.assistantId||'')});
      const errors=[],safe=async(path,fallback)=>{try{return await req(path)}catch(err){const message=String(err?.message||'');if(!message.includes('no longer current')&&!message.includes('stale auth response'))errors.push(path+': '+friendlyError(message));return fallback}};
      // Metadata and dependency health are not scoped to a project. Start
      // them while the authorization list is resolving so the second stage
      // does not add another network round-trip to first paint.
      const metaPromise=safe('/meta',{version:'—',pipeline:{}}),healthPromise=safe('/health',{status:'degraded',dependencies:{}});
      // The project list is the authorization boundary. Keep all project
      // cards hidden until this account-scoped response has arrived; a
      // failed/expired request must leave the UI in loading state, never show
      // a cached or unscoped list from the previous account.
      let assist;
      try{assist=await req('/admin/api/assistants');if(!sameActor()||requested!==state.assistantId)return;state.projectListReady=true}catch(err){if(!sameActor()||requested!==state.assistantId)return;const message=String(err?.message||'');if(!message.includes('no longer current')&&!message.includes('stale auth response'))errors.push('/admin/api/assistants: '+friendlyError(message));state.projectListReady=false;assist={assistants:[]}}
      state.assistants=state.projectListReady?(assist.assistants||[]):[];
      const activeAssistants=state.assistants.filter(x=>!x.deleted_at);
      if(!activeAssistants.some(x=>x.id===state.assistantId)){
        const remembered=localStorage.getItem('research_bee_workspace');
        const preferred=activeAssistants.find(x=>x.id===remembered)||activeAssistants.find(x=>x.slug==='default')||activeAssistants[0];
        state.assistantId=preferred?.id||'';
        if(state.assistantId)localStorage.setItem('research_bee_workspace',state.assistantId);else localStorage.removeItem('research_bee_workspace')
      }
      // Project authorization is the first useful payload on a hard refresh.
      // Paint it immediately instead of waiting for metrics, Telegram and
      // publication data to finish loading; those panels can hydrate after
      // the account's project cards are already usable.
      $('workspaceSelect').innerHTML=activeAssistants.map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('');
      $('workspaceSelect').value=state.assistantId;
      renderAssistants();
      // Authorization and the first localized render are complete. Do not
      // keep visible controls pointer-inert while unrelated health/metrics
      // requests hydrate: a real user can navigate before those requests end.
      window.__researchBeeReleaseLocale?.();
      const authorized=state.assistantId;
      const [meta,health]=await Promise.all([metaPromise,healthPromise]);
      if(!sameActor()||authorized!==state.assistantId)return;
      state.meta=meta;state.health=health;
      if(!state.assistantId){
        Object.assign(state,{metrics:{},sources:[],publications:[],scheduler:{},telegram:{permission:{}},topics:[],runtimeSettings:null,channelConfig:{},feedbackReport:{},business:null,businesses:[],businessAssistantId:'',loadErrors:errors});
        $('workspaceSelect').innerHTML='';$('sidebarVersion').textContent=meta?.version||'—';
        renderDashboard();renderQualityReport({});renderAssistants();renderSources();renderTopics();renderPublications();renderTelegram();renderOperations();renderScheduleGrid();renderChannels();applyRoleVisibility();translateStaticCopy();
        if($('businessGrid'))$('businessGrid').innerHTML='<div class="empty">برای نمایش تنظیمات، یک پروژهٔ مجاز انتخاب کنین.</div>';
        if($('businessSummary'))$('businessSummary').innerHTML='<div class="empty">پروفایل پروژه در دسترس نیست.</div>';
        if($('channelGrid'))$('channelGrid').innerHTML='<div class="empty">برای نمایش کانال‌ها، یک پروژهٔ مجاز انتخاب کنین.</div>';
        return scopeResult();
      }
      const id=state.assistantId;
      const [metrics,sources,pubs,sched,tg,topics,runtime,channel,feedback]=await Promise.all([
        safe('/metrics',{}),safe('/sources',{sources:[]}),safe('/publications/review-queue?limit=1000',{publications:[]}),safe('/scheduler/status',{}),safe('/telegram/readiness',{permission:{}}),safe('/admin/api/topics',{topics:[]}),safe('/admin/api/assistants/'+id+'/runtime-settings',{}),safe('/admin/api/assistants/'+id+'/telegram',{}),safe('/feedback/report?days=30&assistant_id='+encodeURIComponent(id),{})
      ]);
      if(!sameActor()||id!==state.assistantId)return;
      Object.assign(state,{metrics,sources:sources.sources||[],publications:pubs.publications||[],scheduler:sched,telegram:tg,topics:topics.topics||[],runtimeSettings:runtime,channelConfig:channel,feedbackReport:feedback,scheduleSlots:runtime.schedule_slots||[],loadErrors:errors});
      $('sidebarVersion').textContent=meta?.version||state.meta?.version||'—';$('workspaceSelect').innerHTML=state.assistants.filter(x=>!x.deleted_at).map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('');$('workspaceSelect').value=id;if($('scheduleTimezone'))$('scheduleTimezone').textContent=meta.timezone||sched.timezone||'—';if($('maxItemsPerRun'))$('maxItemsPerRun').value=runtime.max_items_per_run??2;if($('freshnessWindowDays'))$('freshnessWindowDays').value=state.language==='en'?String(runtime.freshness_window_days??3):toFaDigits(runtime.freshness_window_days??3);if($('telegramSilentNotifications'))$('telegramSilentNotifications').value=String(Boolean(runtime.telegram_silent_notifications));if($('allowedFeedbackUsers'))$('allowedFeedbackUsers').value=(runtime.allowed_feedback_usernames||[]).join(', ');
      renderDashboard();renderQualityReport(feedback);renderAssistants();renderSources();renderTopics();renderPublications();renderTelegram();renderOperations();renderScheduleGrid();renderChannels();bindRuntimeSave();
      // Business cards, saved views and incident data belong to their own
      // pages.  Do not block the first paint by querying hidden panels.
      if(document.getElementById('view-businesses')?.classList.contains('active'))await refreshBusinessUi();
      if(!sameActor()||id!==state.assistantId)return;
      ensureWorkspaceActions();applyRoleVisibility();translateStaticCopy();localizeVisibleNumbers();toast(errors.length?(state.language==='en'?'Some data failed to load; refresh the affected section.':'بخشی از اطلاعات با خطا بارگذاری شد؛ برای جزئیات همان بخش را بازخوانی کنین.'):(state.language==='en'?'Status refreshed successfully':'وضعیت با موفقیت به‌روز شد'),Boolean(errors.length))
      return scopeResult();
    }
