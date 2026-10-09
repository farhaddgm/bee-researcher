
    // MI-132/133: mount the account dropdown in the sidebar footer and make
    // the Assistant header shell route-independent.
    (function(){
      const sidebar=document.getElementById('sidebar'),foot=sidebar?.querySelector('.sidebar-foot');
      const moveLegacyAccountNav=()=>document.querySelectorAll('.sidebar .nav-btn[data-view="account"]').forEach(button=>{button.classList.add('hidden');button.setAttribute('aria-hidden','true')});
      function labels(){const en=state.language==='en';return en?{account:'Account',security:'Security',support:'Support',logout:'Sign out'}:{account:'حساب کاربری',security:'امنیت',support:'پشتیبانی',logout:'خروج'} }
      function ensureAccountMenu(){
        if(!foot)return;
        let wrap=document.getElementById('sidebarAccountMenuWrap');
        if(!wrap){
          wrap=document.createElement('div');wrap.id='sidebarAccountMenuWrap';wrap.className='sidebar-account';
          wrap.innerHTML='<button type="button" class="sidebar-account-trigger" id="sidebarAccountTrigger" aria-expanded="false" aria-haspopup="menu"><span class="sidebar-account-identity"><span class="sidebar-account-avatar" id="sidebarAccountAvatar">—</span><span class="sidebar-account-name" id="sidebarAccountName">—</span></span><span class="sidebar-account-chevron" aria-hidden="true">⌄</span></button><div class="sidebar-account-menu" id="sidebarAccountMenu" role="menu" hidden><button type="button" data-account-action="account" role="menuitem"><span class="ui-icon" data-icon="user-round" aria-hidden="true"></span><span data-account-label></span></button><button type="button" data-account-action="security" role="menuitem"><span class="ui-icon" data-icon="shield-check" aria-hidden="true"></span><span data-account-label></span></button><button type="button" data-account-action="support" role="menuitem"><span class="ui-icon" data-icon="life-buoy" aria-hidden="true"></span><span data-account-label></span></button><button type="button" data-account-action="logout" role="menuitem"><span class="ui-icon" data-icon="log-out" aria-hidden="true"></span><span data-account-label></span></button></div>';
          foot.insertBefore(wrap,foot.firstChild);
          applyLucideIcons();
          const trigger=wrap.querySelector('#sidebarAccountTrigger'),menu=wrap.querySelector('#sidebarAccountMenu');
          trigger.addEventListener('click',event=>{event.stopPropagation();const open=trigger.getAttribute('aria-expanded')==='true';trigger.setAttribute('aria-expanded',String(!open));menu.hidden=open});
          menu.addEventListener('click',event=>{const action=event.target.closest('[data-account-action]')?.dataset.accountAction;if(!action)return;menu.hidden=true;trigger.setAttribute('aria-expanded','false');if(action==='logout'){document.getElementById('logoutBtn')?.click();return}if(action==='security'){window.setView?.('team');return}if(action==='support'){window.setView?.('support');return}window.setView?.('account')});
          document.addEventListener('click',event=>{if(!wrap.contains(event.target)){menu.hidden=true;trigger.setAttribute('aria-expanded','false')}});
          document.addEventListener('keydown',event=>{if(event.key==='Escape'){menu.hidden=true;trigger.setAttribute('aria-expanded','false')}});
        }
        const copy=labels(),username=String(state.currentUser?.username||'—').trim()||'—';
        const name=document.getElementById('sidebarAccountName'),avatar=document.getElementById('sidebarAccountAvatar');
        if(name)name.textContent=username;if(avatar){const image=state.currentUser?.avatar_url;avatar.classList.remove('ui-avatar-fallback');if(image){const img=document.createElement('img');img.alt='';img.src=image;avatar.replaceChildren(img);}else avatar.textContent=username==='—'?'—':username.slice(0,1).toUpperCase();}
        const menu=document.getElementById('sidebarAccountMenu');if(menu){const labelsByAction={account:copy.account,security:copy.security,support:copy.support,logout:copy.logout};Object.entries(labelsByAction).forEach(([action,label])=>{const target=menu.querySelector('[data-account-action="'+action+'"] [data-account-label]');if(target)target.textContent=label})}
        moveLegacyAccountNav();
      }
      // Other account surfaces (such as the owner avatar editor) can update
      // the identity without rebuilding the whole header.
      window.__researchBeeRefreshSidebarAccount=ensureAccountMenu;
      const applySharedHeader=()=>{document.body.classList.toggle('assistant-header-reference',Boolean(state.currentUser));ensureAccountMenu()};
      const existingSetView=window.setView;if(typeof existingSetView==='function')window.setView=function(name){const result=existingSetView(name);applySharedHeader();return result};
      const existingSetLanguage=window.setLanguage;if(typeof existingSetLanguage==='function')window.setLanguage=function(language){const result=existingSetLanguage(language);applySharedHeader();return result};
      const existingShowApp=window.showApp;if(typeof existingShowApp==='function')window.showApp=function(user){const result=existingShowApp(user);applySharedHeader();return result};
      // The shared header is updated by the authenticated bootstrap, view and
      // language events above.  A 500ms repaint loop only recreated text
      // nodes and made locale normalization look like a digit flicker.
      applySharedHeader();
    })();
