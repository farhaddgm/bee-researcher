
    // MI-141: add the avatar editor only on the owner account page. The
    // sidebar avatar is deliberately only an account-menu trigger.  Earlier
    // code turned the same element into a hidden file-input trigger, which
    // competed with the menu click handler and left a blank avatar/menu in
    // compact navigation.
    (function(){
      const renderAvatarControl=()=>{
        if(!state.currentUser||!(state.currentUser.is_owner||state.currentUser.role==='owner'))return;
        const target=document.querySelector('#view-account .section-card');if(!target||document.getElementById('avatarSettings'))return;
        const username=String(state.currentUser.username||'—'),image=state.currentUser.avatar_url;
        const block=document.createElement('div');block.id='avatarSettings';block.className='avatar-settings';block.innerHTML='<div class="avatar-settings-preview" id="avatarSettingsPreview"></div><div><b>'+(state.language==='en'?'Profile avatar':'تصویر آواتار')+'</b><div class="muted" data-ui-css="declaration-19">'+(state.language==='en'?'Shown next to your name in the sidebar.':'در کنار نام شما در منوی کناری نمایش داده می‌شود.')+'</div><input id="avatarFile" type="file" accept="image/png,image/jpeg,image/webp,image/gif" data-ui-css="declaration-7"></div>';
        const setPreview=value=>{const preview=block.querySelector('#avatarSettingsPreview');if(value){const img=document.createElement('img');img.alt='';img.src=value;preview.replaceChildren(img);}else preview.textContent=username==='—'?'—':username.slice(0,1).toUpperCase();};setPreview(image);
        target.appendChild(block);const input=block.querySelector('#avatarFile');input.addEventListener('change',()=>{const file=input.files?.[0];if(!file)return;if(file.size>350000){toast(state.language==='en'?'Choose an image smaller than 350 KB.':'تصویری کوچک‌تر از ۳۵۰ کیلوبایت انتخاب کنین.',true);input.value='';return}const reader=new FileReader();reader.onload=async()=>{try{const value=String(reader.result||'');await req('/admin/api/account/preferences',{method:'PUT',body:JSON.stringify({avatar_url:value})});state.currentUser.avatar_url=value;setPreview(value);window.__researchBeeRefreshSidebarAccount?.();toast(state.language==='en'?'Avatar saved':'آواتار ذخیره شد')}catch(err){toast(friendlyError(err.message),true)}};reader.readAsDataURL(file)});
      };
      // Avatar settings only depends on the account surface.  Watching the
      // entire document caused every dashboard repaint to run this probe.
      const observer=new MutationObserver(renderAvatarControl);observer.observe(document.getElementById('view-account')||document.body,{childList:true,subtree:true});renderAvatarControl();
    })();
