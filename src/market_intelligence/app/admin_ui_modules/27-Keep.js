
    // Keep this reference treatment isolated to the single Assistant screen.
    (function(){
      const setAssistantReference=()=>{
        const active=document.querySelector('.view.active')?.id||'';
        document.body.classList.toggle('assistant-reference',active==='view-assistants');
      };
      const baseSetView=window.setView;
      if(typeof baseSetView==='function')window.setView=function(name){const result=baseSetView(name);setAssistantReference();return result};
      const baseSetLanguage=window.setLanguage;
      if(typeof baseSetLanguage==='function')window.setLanguage=function(lang){const result=baseSetLanguage(lang);setAssistantReference();return result};
      setAssistantReference();
    })();
