
/* Google sign-in (like Contenter): /admin shows only the Google button when
   it is configured; the unlinked /admin/login-up page also keeps the
   username/password form. Without Google configuration the password form
   stays visible so nobody is locked out. */
(function(){
  const fa=()=>(document.documentElement.lang||'fa').startsWith('fa');
  const passwordMode=document.body.dataset.loginMode==='password';
  const messages={
    not_configured:['ورود با گوگل هنوز پیکربندی نشده است.','Google sign-in is not configured yet.'],
    cancelled:['ورود با گوگل لغو شد.','Google sign-in was cancelled.'],
    expired:['مهلت ورود تمام شد؛ دوباره تلاش کنید.','The sign-in attempt expired; please try again.'],
    not_gmail:['فقط حساب‌های ‎@gmail.com پذیرفته می‌شوند.','Only @gmail.com accounts are accepted.'],
    not_allowed:['این حساب جیمیل اجازهٔ ورود ندارد.','This Gmail account is not allowed to sign in.'],
    inactive:['این حساب غیرفعال است.','This account is disabled.'],
    rate_limited:['تلاش‌های زیاد؛ کمی بعد دوباره امتحان کنید.','Too many attempts; please try again later.'],
    failed:['ورود با گوگل ناموفق بود.','Google sign-in failed.']
  };
  const params=new URLSearchParams(location.search),code=params.get('login_error');
  if(code&&messages[code]){
    const show=()=>{const box=document.getElementById('loginMsg');if(box)box.textContent=messages[code][fa()?0:1]};
    show();setTimeout(show,800);
    history.replaceState(null,'',location.pathname);
  }
  const button=document.getElementById('googleLoginBtn'),login=document.getElementById('login');
  const label=()=>{if(button)button.textContent=fa()?'ورود با گوگل':'Sign in with Google'};
  label();
  fetch('/auth/providers',{credentials:'same-origin'}).then(r=>r.ok?r.json():{google:false}).catch(()=>({google:false})).then(p=>{
    if(!p||!p.google||!button)return;
    button.hidden=false;
    if(!passwordMode&&login)login.classList.add('google-only');
  });
  new MutationObserver(label).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
})();
