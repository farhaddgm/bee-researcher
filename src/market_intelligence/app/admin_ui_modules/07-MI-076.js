
    // MI-076: changing language must not replace the logout icon with plain text.
    (function(){
      const currentSetLanguage=window.setLanguage;
      if(typeof currentSetLanguage!=='function')return;
      window.setLanguage=function(lang){
        const button=document.getElementById('logoutBtn');
        const icon=button?.querySelector('[data-icon]')?.outerHTML||'';
        currentSetLanguage(lang);
        if(!button)return;
        const label=state.language==='en'?'Sign out':'خروج';
        button.innerHTML=`${icon}<span id="logoutLabel" class="btn-label">${label}</span>`;
        applyLucideIcons();
      };
      const button=document.getElementById('logoutBtn');
      if(button&&!button.querySelector('#logoutLabel')){const icon=button.querySelector('[data-icon]')?.outerHTML||'';button.innerHTML=`${icon}<span id="logoutLabel" class="btn-label">${state.language==='en'?'Sign out':'خروج'}</span>`;applyLucideIcons()}
    })();
