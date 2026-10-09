
    // MI-095: repair the owner account route, localize settings inputs, and
    // keep Telegram readiness after the destination configuration card.
    (function(){
      const accountButton=document.querySelector('[data-view="account"]');
      if(accountButton)accountButton.onclick=event=>{event.preventDefault();event.stopPropagation();setView('account')};
      document.addEventListener('click',event=>{const button=event.target?.closest?.('[data-view="account"]');if(!button)return;event.preventDefault();event.stopPropagation();setView('account')},true);

      const settingIds=['limitMaxSources','limitMaxTopics','limitMaxFreshness','limitMaxItems','limitMaxBusinesses','limitMaxProjects'];
      const localizeSettingsNumbers=()=>{const english=state.language==='en';settingIds.forEach(id=>{const input=$(id);if(!input)return;input.type='text';input.inputMode='numeric';input.setAttribute('pattern','[0-9۰-۹]*');const latin=toLatinDigits(input.value);if(latin!==''&&/^[0-9]+$/.test(latin))input.value=english?latin:toFaDigits(latin)})};
      window.__researchBeeLocalizeSettingsNumbers=localizeSettingsNumbers;
      const updateScheduleTitle=()=>{const heading=document.querySelector('#view-schedule .schedule-matrix-card h3');if(heading){heading.dataset.faText='زمان‌بندی';heading.textContent=state.language==='en'?'Schedule':'زمان‌بندی'}};
      const oldLanguage=setLanguage;setLanguage=function(lang){oldLanguage(lang);localizeSettingsNumbers();updateScheduleTitle()};
      const oldLoadAll=loadAll;loadAll=async function(){const result=await oldLoadAll();localizeSettingsNumbers();return result};
      document.addEventListener('click',event=>{if(event.target?.id!=='saveLimitsBtn')return;settingIds.forEach(id=>{const input=$(id);if(input)input.value=toLatinDigits(input.value)});setTimeout(localizeSettingsNumbers,0)},true);
      const schedule=document.querySelector('#view-schedule .schedule-layout'),matrix=document.querySelector('#view-schedule .schedule-matrix-card'),readiness=document.querySelector('#view-schedule .schedule-layout > .section-card:not(#channelSettingsCard)'),channels=document.getElementById('channelSettingsCard');
      if(schedule&&matrix)schedule.prepend(matrix);
      if(schedule&&readiness&&channels)schedule.insertBefore(channels,readiness);
      localizeSettingsNumbers();updateScheduleTitle();
    })();
