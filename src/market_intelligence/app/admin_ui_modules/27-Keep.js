
    // Keep this reference treatment isolated to the single Assistant screen.
    (function(){
      const setAssistantReference=()=>{
        const active=document.querySelector('.view.active')?.id||'';
        document.body.classList.toggle('assistant-reference',active==='view-assistants');
      };
      window.BeeAdminLifecycle.register('assistant-reference', ['setView','setLanguage'], {after:setAssistantReference});
      setAssistantReference();
    })();
