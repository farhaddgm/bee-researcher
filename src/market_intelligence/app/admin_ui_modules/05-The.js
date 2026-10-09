
    (function(){
      const bindLoginRecovery=()=>{
        const form=document.getElementById('loginForm'),button=document.getElementById('loginSubmit');
        if(!form||!button||button.dataset.loginRecoveryBound==='1')return;
        button.dataset.loginRecoveryBound='1';button.type='submit';
        let pending=false;
        const message=value=>{const target=document.getElementById('loginMsg');if(target)target.textContent=value};
        const directLogin=async event=>{
          event?.preventDefault();
          if(pending)return;
          // The normal handler is installed as the form's onsubmit property.
          // Dispatching a submit event preserves its validation and avoids a
          // second request caused by the button's native activation.
          if(typeof form.onsubmit==='function'){
            form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
            return;
          }
          const username=(document.getElementById('loginUser')?.value||'').trim();
          const password=document.getElementById('loginPass')?.value||'';
          const fa=(document.documentElement.lang||'en')==='fa';
          if(!username){message(fa?'نام کاربری را وارد کنین.':'Please enter your username.');document.getElementById('loginUser')?.focus();return}
          if(!password){message(fa?'رمز عبور را وارد کنین.':'Please enter your password.');document.getElementById('loginPass')?.focus();return}
          pending=true;button.disabled=true;button.setAttribute('aria-busy','true');
          const original=button.textContent;button.textContent=fa?'در حال ورود…':'Signing in…';
          try{
            const controller=typeof AbortController==='undefined'?null:new AbortController();
            const timer=controller?setTimeout(()=>controller.abort(),15000):0;
            let response;
            try{response=await fetch('/admin/api/login',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password}),...(controller?{signal:controller.signal}:{})})}finally{if(timer)clearTimeout(timer)}
            let body={};try{body=await response.json()}catch(_){body={}};
            if(!response.ok){const detail=Array.isArray(body.detail)?body.detail.map(item=>item?.msg||item?.detail||String(item)).join('؛ '):String(body.detail||'');const disabled=/account[_ ]disabled/i.test(detail);throw Error(disabled?(fa?'حساب شما غیرفعال است. لطفاً با مدیر حساب‌ها ارتباط بگیرین.':'Your account is disabled. Please contact the account administrator.'):(fa?'ورود انجام نشد. لطفاً نام کاربری و رمز عبور را بررسی کنین.':'We could not sign you in. Please check your username and password.'))}
            window.location.reload();
          }catch(error){message(error.message|| (fa?'ورود انجام نشد. لطفاً دوباره تلاش کنین.':'We could not sign you in. Please try again.'));button.disabled=false;button.removeAttribute('aria-busy');button.textContent=original;pending=false}
        };
        // Capture handles Enter and browsers that do not activate a submit
        // button normally; the click listener handles the reported no-op case.
        form.addEventListener('submit',event=>{if(typeof form.onsubmit!=='function')directLogin(event)},{capture:true});
        button.addEventListener('click',directLogin);
      };
      if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bindLoginRecovery,{once:true});else bindLoginRecovery();
    })();
