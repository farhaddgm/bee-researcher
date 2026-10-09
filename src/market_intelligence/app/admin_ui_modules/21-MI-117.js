
    // MI-117: expose the service timezone in the owner settings view. The
    // value is stored in the assistant runtime config and the scheduler uses
    // it when calculating both processing and publication slots.
    (function(){
      const zones=[['Europe/Berlin','Berlin (Germany)'],['Asia/Tehran','Tehran (Iran)'],['UTC','UTC'],['Europe/London','London (UK)'],['America/New_York','New York (US)'],['Asia/Dubai','Dubai (UAE)'],['Asia/Tokyo','Tokyo (Japan)']];
      const ensure=()=>{
        const view=document.getElementById('view-settings'),grid=view?.querySelector('.limits-grid');
        if(!view||!grid||document.getElementById('serviceTimezone'))return;
        const field=document.createElement('div');field.className='field';field.innerHTML='<label id="serviceTimezoneLabel">Service timezone</label><select id="serviceTimezone"></select><small id="serviceTimezoneHelp" class="muted">Publishing and processing hours use this timezone.</small>';
        grid.appendChild(field);
        const select=document.getElementById('serviceTimezone');select.innerHTML=zones.map(([value,label])=>`<option value="${value}">${label}</option>`).join('');
      };
      const copy=()=>{ensure();const en=state.language==='en';const label=$('serviceTimezoneLabel'),help=$('serviceTimezoneHelp');if(label)label.textContent=en?'Service timezone':'منطقهٔ زمانی سرویس';if(help)help.textContent=en?'Publishing and processing hours use this timezone.':'ساعت‌های پردازش و انتشار با این منطقهٔ زمانی محاسبه می‌شوند.'};
      const load=async()=>{copy();if(!state.assistantId||!$('serviceTimezone'))return;const active=document.getElementById('view-settings')?.classList.contains('active')||document.getElementById('view-schedule')?.classList.contains('active');if(!active)return;try{const runtime=state.runtimeSettings||await req('/admin/api/assistants/'+state.assistantId+'/runtime-settings');$('serviceTimezone').value=runtime.timezone||'Europe/Berlin'}catch{ $('serviceTimezone').value='Europe/Berlin' }};
      const previousLoadAll=loadAll;loadAll=async function(){const result=await previousLoadAll();await load();return result};
      const previousSetLanguage=setLanguage;setLanguage=function(lang){previousSetLanguage(lang);copy()};
      document.addEventListener('click',async event=>{if(event.target?.id!=='saveLimitsBtn'||!$('serviceTimezone')||!state.assistantId)return;try{await req('/admin/api/assistants/'+state.assistantId+'/runtime-settings',{method:'PUT',body:JSON.stringify({timezone:$('serviceTimezone').value})});if($('limitsMsg')){$('limitsMsg').textContent=state.language==='en'?'Settings saved':'تنظیمات ذخیره شد';$('limitsMsg').className='success'}}catch(err){if($('limitsMsg')){$('limitsMsg').textContent=friendlyError(err.message);$('limitsMsg').className='error'}toast(friendlyError(err.message),true)}});
      copy();
    })();
