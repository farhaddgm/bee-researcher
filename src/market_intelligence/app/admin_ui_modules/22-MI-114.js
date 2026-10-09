
    // MI-114/115/116: keep navigation semantics explicit: account icon uses
    // the user glyph, settings belongs to configuration, and feedback lives
    // in the workspace group alongside the review queue.
    (function(){
      const groups=[...document.querySelectorAll('#sidebar .nav-group')],workspace=groups[0],configuration=groups[1],control=groups[2];
      const account=document.querySelector('[data-view="account"]'),accountIcon=account?.querySelector('.nav-icon');
      if(accountIcon){accountIcon.dataset.icon='user-round';applyLucideIcons()}
      const settings=document.querySelector('[data-view="settings"]');if(settings&&configuration)configuration.appendChild(settings);
      const quality=document.querySelector('[data-view="quality"]');if(quality&&workspace)workspace.appendChild(quality);
      const team=document.querySelector('[data-view="team"]'),operations=document.querySelector('[data-view="operations"]');
      if(control){const label=control.querySelector('.nav-label');if(label){label.textContent=state.language==='en'?'Account settings':'تنظیمات حساب';label.dataset.labelFa='تنظیمات حساب';label.dataset.labelEn='Account settings';label.removeAttribute('aria-hidden');label.style.display='';}if(account)control.appendChild(account);if(team)control.appendChild(team);if(operations)control.appendChild(operations)}
    })();
