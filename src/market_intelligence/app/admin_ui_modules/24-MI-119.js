
    // MI-119/124: move the complete security workspace into Account. The
    // standalone Security navigation item is removed; the old route remains
    // a safe internal alias for cached links and keyboard shortcuts.
    (function(){
    const version=document.getElementById('sidebarVersion');if(version)version.textContent='v3.30.1';
      const removeStandaloneSecurity=()=>document.querySelector('[data-view="team"]')?.remove();
      const moveSecurity=()=>{
        const account=document.getElementById('view-account'),team=document.getElementById('view-team');
        if(!account||!team||account.dataset.securityMoved==='true')return;
        const head=team.querySelector('.page-head'),grid=team.querySelector('.grid.two-col');
        if(!head||!grid)return;
        const panel=document.createElement('section');panel.id='accountSecurityPanel';panel.className='account-security-panel';
        const title=head.querySelector('h2'),subtitle=head.querySelector('p');if(title)title.id='accountSecurityTitle';if(subtitle)subtitle.id='accountSecuritySubtitle';
        panel.append(head,grid);account.append(panel);team.classList.add('hidden');team.dataset.movedToAccount='true';account.dataset.securityMoved='true';
      };
      const renderCopy=()=>{moveSecurity();removeStandaloneSecurity();const en=state.language==='en',title=document.getElementById('accountSecurityTitle'),subtitle=document.getElementById('accountSecuritySubtitle');if(title)title.textContent=en?'Account security':'امنیت حساب';if(subtitle)subtitle.textContent=en?'Manage users, roles and active sessions.':'کاربران، نقش‌ها و نشست‌های فعال را مدیریت کنین.'};
      const previousLoadAll=loadAll;loadAll=async function(){const result=await previousLoadAll();renderCopy();return result};
      const previousSetLanguage=setLanguage;setLanguage=function(lang){previousSetLanguage(lang);renderCopy()};
      const previousSetView=setView;setView=function(name){if(name==='team'){renderCopy();previousSetView('account');if(typeof loadUsers==='function')loadUsers();document.getElementById('accountSecurityPanel')?.scrollIntoView({block:'start'});return}previousSetView(name);if(name==='account'&&typeof loadUsers==='function')loadUsers()};
      renderCopy();
    window.__researchBeeState=state;window.state=state;window.$=$;window.req=req;window.modal=modal;window.closeModal=closeModal;window.toast=toast;window.esc=esc;window.friendlyError=friendlyError;window.toFaDigits=toFaDigits;
    ensureFeedbackLearningPanel();ensureKnowledgePanel();ensurePrivacyPanel();const privacyPanel=$('privacyControlPanel'),securityPanel=$('accountSecurityPanel');if(privacyPanel&&securityPanel)securityPanel.appendChild(privacyPanel);
    function localizeIdeaPanels(){const en=state.language==='en',feedback=$('feedbackLearningPanel'),knowledge=$('knowledgeLibraryPanel'),privacy=$('privacyControlPanel');if(feedback){const h=feedback.querySelector('h3'),s=feedback.querySelector('span'),buttons=feedback.querySelectorAll('button');if(h)h.textContent=en?'Feedback learning center':'مرکز یادگیری بازخورد';if(s)s.textContent=en?'Explainable report; no automatic production change':'گزارش توضیح‌پذیر؛ تغییر خودکار اعمال نمی‌شود';if(buttons[0])buttons[0].textContent=en?'Refresh':'بازخوانی';if(buttons[1])buttons[1].textContent=en?'Rollback last change':'بازگردانی آخرین تغییر'}if(knowledge){const h=knowledge.querySelector('h3'),b=knowledge.querySelector('button'),labels=knowledge.querySelectorAll('.detail-item span');if(h)h.textContent=en?'Business knowledge library':'کتابخانه دانش کسب‌وکار';if(b)b.textContent=en?'Edit knowledge':'ویرایش دانش';['Key facts','Products and services','Markets','Differentiators','Goals','References'].forEach((label,i)=>{if(en&&labels[i])labels[i].textContent=label})}if(privacy){const h=privacy.querySelector('h3'),s=privacy.querySelector('span'),buttons=privacy.querySelectorAll('button'),labels=privacy.querySelectorAll('label');if(h)h.textContent=en?'Privacy and compliance':'حریم خصوصی و انطباق';if(s)s.textContent=en?'Project retention and safe data export':'تنظیم نگهداری و خروجی امن دادهٔ پروژه';if(buttons[0])buttons[0].textContent=en?'Save':'ذخیره';if(buttons[1])buttons[1].textContent=en?'Export data':'خروجی داده';if(labels[0])labels[0].childNodes[0].textContent=en?'Retention (days)':'مدت نگهداری (روز)';if(labels[1])labels[1].childNodes[0].textContent=en?'Data region':'منطقه داده';if(labels[2])labels[2].lastChild.textContent=en?' Allow data export':' خروجی داده مجاز باشد'}}
    const previousSetLanguageIdea=setLanguage;setLanguage=function(lang){previousSetLanguageIdea(lang);localizeIdeaPanels()};localizeIdeaPanels();
    const loadAllWithKnowledge=loadAll;loadAll=async function(){await loadAllWithKnowledge();if(document.getElementById('view-businesses')?.classList.contains('active')&&window.loadKnowledge)await window.loadKnowledge();if(document.getElementById('view-account')?.classList.contains('active')&&window.loadPrivacy)await window.loadPrivacy();localizeIdeaPanels()};
    const roleVisibilityWithShortcuts=applyRoleVisibility;applyRoleVisibility=function(){roleVisibilityWithShortcuts();const owner=Boolean(state.currentUser?.is_owner||state.currentUser?.role==='owner');const quick=$('quickAssistantBtn');if(quick)quick.classList.toggle('hidden',!owner)};applyRoleVisibility();if($('quickAssistantBtn'))$('quickAssistantBtn').onclick=openQuickAssistantModal;
    })();
