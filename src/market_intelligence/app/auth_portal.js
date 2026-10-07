/* Shared eight-language identity UI. No secrets, timer-based translations or fallback forms. */
(() => {
  'use strict';
  let securityLastActivity=Date.now();
  for(const event of ['pointerdown','keydown'])document.addEventListener(event,()=>{securityLastActivity=Date.now()},{passive:true});
  const securityFetch=window.fetch.bind(window);
  window.fetch=(input,init={})=>{
    const url=new URL(typeof input==='string'?input:input.url,location.href);
    if(url.origin===location.origin && (url.pathname.startsWith('/admin/api/')||url.pathname.startsWith('/user/api/'))){
      const headers=new Headers(init.headers||(input instanceof Request?input.headers:undefined));
      if(!document.hidden&&Date.now()-securityLastActivity<30000)headers.set('X-User-Activity','1');
      const method=String(init.method||(input instanceof Request?input.method:'GET')).toUpperCase();
      if(!['GET','HEAD','OPTIONS'].includes(method)){
        const name=url.pathname.startsWith('/user/api/')?'research_bee_user_csrf':'research_bee_admin_csrf';
        const cookie=document.cookie.split(';').map(x=>x.trim()).find(x=>x.startsWith(name+'='));
        if(cookie)headers.set('X-CSRF-Token',decodeURIComponent(cookie.slice(name.length+1)));
      }
      init={...init,headers};
    }
    return securityFetch(input,init);
  };
  const languages=['fa','en','tr','ar','es','it','de','fr'];
  const words={
    title:['ورود به Bee Researcher','Sign in to Bee Researcher','Bee Researcher’a giriş','تسجيل الدخول إلى Bee Researcher','Iniciar sesión en Bee Researcher','Accedi a Bee Researcher','Bei Bee Researcher anmelden','Se connecter à Bee Researcher'],
    google:['ورود با گوگل','Sign in with Google','Google ile giriş yap','تسجيل الدخول باستخدام Google','Iniciar sesión con Google','Accedi con Google','Mit Google anmelden','Se connecter avec Google'],
    allowed:['فقط حساب‌های مجاز می‌توانند وارد شوند.','Only authorized accounts can sign in.','Yalnızca yetkili hesaplar giriş yapabilir.','يمكن للحسابات المصرح لها فقط تسجيل الدخول.','Solo pueden acceder las cuentas autorizadas.','Possono accedere solo gli account autorizzati.','Nur autorisierte Konten können sich anmelden.','Seuls les comptes autorisés peuvent se connecter.'],
    email:['ایمیل یا نام کاربری حساب قدیمی','Email or legacy username','E-posta veya eski kullanıcı adı','البريد الإلكتروني أو اسم المستخدم القديم','Correo electrónico o usuario anterior','Email o nome utente precedente','E-Mail oder bisheriger Benutzername','E-mail ou ancien nom d’utilisateur'],
    password:['رمز عبور','Password','Parola','كلمة المرور','Contraseña','Password','Passwort','Mot de passe'],
    signin:['ورود به حساب','Sign in','Giriş yap','تسجيل الدخول','Iniciar sesión','Accedi','Anmelden','Se connecter'],
    refresh:['بازخوانی','Refresh','Yenile','تحديث','Actualizar','Aggiorna','Aktualisieren','Actualiser'],
    currentPasswordWrong:['رمز فعلی درست نیست.','The current password is incorrect.','Mevcut parola yanlış.','كلمة المرور الحالية غير صحيحة.','La contraseña actual es incorrecta.','La password attuale non è corretta.','Das aktuelle Passwort ist falsch.','Le mot de passe actuel est incorrect.'],
    not_configured:['ورود گوگلی هنوز توسط مدیر سرور پیکربندی نشده است.','Google sign-in has not been configured by the server administrator.','Google ile giriş sunucu yöneticisi tarafından henüz yapılandırılmadı.','لم يقم مسؤول الخادم بإعداد تسجيل الدخول باستخدام Google بعد.','El administrador aún no ha configurado el acceso con Google.','L’amministratore non ha ancora configurato l’accesso con Google.','Die Google-Anmeldung wurde noch nicht eingerichtet.','L’administrateur n’a pas encore configuré la connexion Google.'],
    cancelled:['ورود با گوگل لغو شد.','Google sign-in was cancelled.','Google ile giriş iptal edildi.','تم إلغاء تسجيل الدخول باستخدام Google.','Se canceló el acceso con Google.','Accesso con Google annullato.','Die Google-Anmeldung wurde abgebrochen.','La connexion Google a été annulée.'],
    expired:['مهلت ورود تمام شد؛ دوباره تلاش کنید.','The sign-in attempt expired. Please try again.','Giriş süresi doldu. Tekrar deneyin.','انتهت مهلة تسجيل الدخول. حاول مرة أخرى.','La solicitud caducó. Inténtalo de nuevo.','La richiesta è scaduta. Riprova.','Der Anmeldeversuch ist abgelaufen. Bitte erneut versuchen.','La demande a expiré. Réessayez.'],
    not_gmail:['فقط آدرس‌های Gmail و Googlemail پذیرفته می‌شوند.','Only Gmail and Googlemail addresses are accepted.','Yalnızca Gmail ve Googlemail adresleri kabul edilir.','تُقبل عناوين Gmail وGooglemail فقط.','Solo se aceptan direcciones Gmail y Googlemail.','Sono accettati solo indirizzi Gmail e Googlemail.','Nur Gmail- und Googlemail-Adressen werden akzeptiert.','Seules les adresses Gmail et Googlemail sont acceptées.'],
    not_allowed:['این حساب اجازهٔ ورود به این بخش را ندارد.','This account is not authorized for this portal.','Bu hesabın bu portala erişim izni yok.','هذا الحساب غير مصرح له بالدخول إلى هذه البوابة.','Esta cuenta no tiene acceso a este portal.','Questo account non è autorizzato per questo portale.','Dieses Konto ist für dieses Portal nicht freigeschaltet.','Ce compte n’est pas autorisé à accéder à ce portail.'],
    inactive:['این حساب غیرفعال است.','This account is disabled.','Bu hesap devre dışı.','هذا الحساب معطل.','Esta cuenta está desactivada.','Questo account è disattivato.','Dieses Konto ist deaktiviert.','Ce compte est désactivé.'],
    rate_limited:['تلاش‌های زیادی انجام شده؛ کمی بعد دوباره امتحان کنید.','Too many attempts. Please try again later.','Çok fazla deneme. Daha sonra tekrar deneyin.','محاولات كثيرة. حاول لاحقًا.','Demasiados intentos. Inténtalo más tarde.','Troppi tentativi. Riprova più tardi.','Zu viele Versuche. Bitte später erneut versuchen.','Trop de tentatives. Réessayez plus tard.'],
    failed:['ورود با گوگل ناموفق بود؛ دوباره تلاش کنید.','Google sign-in failed. Please try again.','Google ile giriş başarısız. Tekrar deneyin.','فشل تسجيل الدخول باستخدام Google. حاول مرة أخرى.','Falló el acceso con Google. Inténtalo de nuevo.','Accesso con Google non riuscito. Riprova.','Google-Anmeldung fehlgeschlagen. Bitte erneut versuchen.','La connexion Google a échoué. Réessayez.'],
    accounts:['مدیریت حساب‌ها و دسترسی','Accounts and access','Hesaplar ve erişim','الحسابات والوصول','Cuentas y acceso','Account e accessi','Konten und Zugriffsrechte','Comptes et accès'],
    directory:['روش ورود، دستیارهای مجاز و دسترسی پرتال User مستقل از هم هستند.','Sign-in method, assistant access and User portal permissions are independent.','Giriş yöntemi, asistan erişimi ve User portalı izinleri birbirinden bağımsızdır.','طريقة الدخول والوصول إلى المساعدين وأذونات بوابة User مستقلة.','El método de acceso, los asistentes y los permisos del portal User son independientes.','Metodo di accesso, assistenti e permessi del portale User sono indipendenti.','Anmeldemethode, Assistentenzugriff und User-Portal-Rechte sind unabhängig.','Le mode de connexion, les assistants et les droits du portail User sont indépendants.'],
    add:['افزودن حساب','Add account','Hesap ekle','إضافة حساب','Añadir cuenta','Aggiungi account','Konto hinzufügen','Ajouter un compte'],
    edit:['ویرایش','Edit','Düzenle','تعديل','Editar','Modifica','Bearbeiten','Modifier'],
    remove:['حذف حساب','Delete account','Hesabı sil','حذف الحساب','Eliminar cuenta','Elimina account','Konto löschen','Supprimer le compte'],
    removeGoogle:['لغو ورود گوگلی','Revoke Google sign-in','Google ile girişi kaldır','إلغاء الدخول باستخدام Google','Revocar acceso con Google','Revoca accesso con Google','Google-Anmeldung entziehen','Retirer la connexion Google'],
    removeHint:['حساب حذف می‌شود، اما خبرها و محتوای پروژه‌ها باقی می‌مانند.','The account will be deleted. Project content and news will remain.','Hesap silinir. Proje içeriği ve haberler korunur.','سيُحذف الحساب وتبقى أخبار المشاريع ومحتوياتها.','Se eliminará la cuenta. Se conservarán las noticias y el contenido.','L’account sarà eliminato. Notizie e contenuti resteranno.','Das Konto wird gelöscht. Nachrichten und Projektinhalte bleiben erhalten.','Le compte sera supprimé. Les contenus et actualités seront conservés.'],
    revokeHint:['اگر حساب رمز داخلی داشته باشد، ورود رمزی باقی می‌ماند؛ در غیر این صورت حساب غیرفعال می‌شود.','Password access remains if an internal password exists; otherwise the account is disabled.','Dahili parola varsa parola ile giriş devam eder; yoksa hesap devre dışı bırakılır.','يبقى الدخول بكلمة المرور إن وُجدت، وإلا يُعطل الحساب.','Si existe contraseña interna, se mantiene ese acceso; si no, se desactiva la cuenta.','Se esiste una password interna, tale accesso resta; altrimenti l’account viene disattivato.','Mit internem Passwort bleibt die Passwort-Anmeldung möglich; sonst wird das Konto deaktiviert.','L’accès par mot de passe reste possible s’il existe ; sinon le compte est désactivé.'],
    name:['نام نمایشی','Display name','Görünen ad','الاسم المعروض','Nombre visible','Nome visualizzato','Anzeigename','Nom affiché'],
    address:['ایمیل','Email','E-posta','البريد الإلكتروني','Correo electrónico','Email','E-Mail','E-mail'],
    role:['نقش','Role','Rol','الدور','Rol','Ruolo','Rolle','Rôle'],
    method:['روش ورود','Sign-in method','Giriş yöntemi','طريقة الدخول','Método de acceso','Metodo di accesso','Anmeldemethode','Mode de connexion'],
    googleOnly:['فقط گوگل','Google only','Yalnızca Google','Google فقط','Solo Google','Solo Google','Nur Google','Google uniquement'],
    passwordOnly:['فقط رمز عبور','Password only','Yalnızca parola','كلمة المرور فقط','Solo contraseña','Solo password','Nur Passwort','Mot de passe uniquement'],
    both:['گوگل و رمز عبور','Google and password','Google ve parola','Google وكلمة المرور','Google y contraseña','Google e password','Google und Passwort','Google et mot de passe'],
    owner:['مالک','Owner','Sahip','المالك','Propietario','Proprietario','Eigentümer','Propriétaire'],
    ownersOnly:['فقط مالک','Owners only','Yalnızca sahip','للمالك فقط','Solo propietario','Solo proprietario','Nur Eigentümer','Propriétaire uniquement'],
    admin:['مدیر','Administrator','Yönetici','مسؤول','Administrador','Amministratore','Administrator','Administrateur'],
    assistant_admin:['مدیر دستیار','Assistant administrator','Asistan yöneticisi','مسؤول المساعد','Administrador del asistente','Amministratore dell’assistente','Assistentenadministrator','Administrateur d’assistant'],
    editor:['ویرایشگر','Editor','Editör','محرر','Editor','Redattore','Redakteur','Éditeur'],
    analyst:['تحلیل‌گر','Analyst','Analist','محلل','Analista','Analista','Analyst','Analyste'],
    viewer:['مشاهده‌گر','Viewer','Görüntüleyici','مشاهد','Lector','Lettore','Betrachter','Lecteur'],
    status:['وضعیت','Status','Durum','الحالة','Estado','Stato','Status','État'],
    active:['فعال','Active','Aktif','نشط','Activo','Attivo','Aktiv','Actif'],
    disabled:['غیرفعال','Disabled','Devre dışı','معطل','Desactivado','Disattivato','Deaktiviert','Désactivé'],
    search:['جست‌وجوی نام یا ایمیل','Search name or email','Ad veya e-posta ara','البحث بالاسم أو البريد','Buscar nombre o correo','Cerca nome o email','Name oder E-Mail suchen','Rechercher un nom ou un e-mail'],
    empty:['حسابی پیدا نشد.','No accounts found.','Hesap bulunamadı.','لم يتم العثور على حسابات.','No se encontraron cuentas.','Nessun account trovato.','Keine Konten gefunden.','Aucun compte trouvé.'],
    loading:['در حال بارگذاری…','Loading…','Yükleniyor…','جارٍ التحميل…','Cargando…','Caricamento…','Wird geladen…','Chargement…'],
    previous:['قبلی','Previous','Önceki','السابق','Anterior','Precedente','Zurück','Précédent'],
    next:['بعدی','Next','Sonraki','التالي','Siguiente','Successivo','Weiter','Suivant'],
    save:['ذخیره','Save','Kaydet','حفظ','Guardar','Salva','Speichern','Enregistrer'],
    cancel:['انصراف','Cancel','İptal','إلغاء','Cancelar','Annulla','Abbrechen','Annuler'],
    saved:['تغییرات ذخیره شد.','Changes saved.','Değişiklikler kaydedildi.','تم حفظ التغييرات.','Cambios guardados.','Modifiche salvate.','Änderungen gespeichert.','Modifications enregistrées.'],
    requestFailed:['درخواست انجام نشد. دوباره تلاش کنید.','Request failed. Please try again.','İşlem başarısız. Tekrar deneyin.','فشل الطلب. حاول مرة أخرى.','La solicitud falló. Inténtalo de nuevo.','Richiesta non riuscita. Riprova.','Anfrage fehlgeschlagen. Bitte erneut versuchen.','La demande a échoué. Réessayez.'],
    projects:['دستیارهای مجاز','Authorized assistants','Yetkili asistanlar','المساعدون المصرح بهم','Asistentes autorizados','Assistenti autorizzati','Freigegebene Assistenten','Assistants autorisés'],
    portal:['دسترسی به بک‌آفیس User','User portal access','User portalına erişim','الوصول إلى بوابة User','Acceso al portal User','Accesso al portale User','Zugriff auf das User-Portal','Accès au portail User'],
    feedback:['اجازهٔ بازخورد روی خبرها','Allow news feedback','Haberlere geri bildirim izni','السماح بالتعليق على الأخبار','Permitir comentarios sobre noticias','Consenti feedback sulle notizie','Nachrichten-Feedback erlauben','Autoriser les avis sur les actualités'],
    passwordHint:['۱۵ تا ۱۲۸ کاراکتر؛ خالی بگذارید تا رمز قبلی حفظ شود.','15–128 characters. Leave blank to keep the current password.','15–128 karakter. Mevcut parolayı korumak için boş bırakın.','من 15 إلى 128 حرفًا. اتركه فارغًا للاحتفاظ بكلمة المرور الحالية.','15–128 caracteres. Déjalo vacío para mantener la contraseña actual.','15–128 caratteri. Lascia vuoto per mantenere la password attuale.','15–128 Zeichen. Leer lassen, um das bisherige Passwort zu behalten.','15 à 128 caractères. Laissez vide pour conserver le mot de passe actuel.'],
    methodHint:['فقط مالک می‌تواند اجازهٔ ورود گوگلی را تغییر دهد.','Only the owner can change Google sign-in permission.','Google ile giriş iznini yalnızca sahip değiştirebilir.','يمكن للمالك فقط تغيير إذن الدخول باستخدام Google.','Solo el propietario puede cambiar el permiso de Google.','Solo il proprietario può modificare il permesso Google.','Nur der Eigentümer kann die Google-Freigabe ändern.','Seul le propriétaire peut modifier l’autorisation Google.'],
    portalHint:['مجوز User، دستیار جدیدی اضافه نمی‌کند؛ بازخورد نیز مجوز جداگانه دارد.','User access adds no assistants. Feedback needs a separate permission.','User erişimi yeni asistan eklemez. Geri bildirim ayrı izin gerektirir.','الوصول إلى User لا يضيف مساعدين. التعليق يحتاج إذنًا منفصلًا.','El acceso a User no añade asistentes. Los comentarios requieren otro permiso.','L’accesso User non aggiunge assistenti. Il feedback richiede un permesso distinto.','User-Zugriff fügt keine Assistenten hinzu. Feedback benötigt eine eigene Freigabe.','L’accès User n’ajoute aucun assistant. Les avis nécessitent une autorisation distincte.'],
    currentPassword:['رمز فعلی','Current password','Mevcut parola','كلمة المرور الحالية','Contraseña actual','Password attuale','Aktuelles Passwort','Mot de passe actuel'],
    ownAccount:['حساب شما','Your account','Hesabınız','حسابك','Tu cuenta','Il tuo account','Ihr Konto','Votre compte'],
    googlePasswordHint:['این حساب رمز داخلی ندارد؛ رمز گوگل را در حساب گوگل مدیریت کنید.','This account has no internal password. Manage your Google password in Google.','Bu hesabın dahili parolası yok. Google parolanızı Google hesabınızda yönetin.','هذا الحساب بلا كلمة مرور داخلية. أدر كلمة مرور Google في حساب Google.','Esta cuenta no tiene contraseña interna. Gestiona la de Google en Google.','Questo account non ha password interna. Gestisci quella Google nel tuo account Google.','Dieses Konto hat kein internes Passwort. Verwalten Sie Ihr Google-Passwort bei Google.','Ce compte n’a pas de mot de passe interne. Gérez votre mot de passe Google chez Google.'],
    changePassword:['تغییر رمز عبور','Change password','Parolayı değiştir','تغيير كلمة المرور','Cambiar contraseña','Cambia password','Passwort ändern','Changer le mot de passe'],
    lastLogin:['آخرین ورود','Last sign-in','Son giriş','آخر دخول','Último acceso','Ultimo accesso','Letzte Anmeldung','Dernière connexion'],
    googleReady:['ورود گوگلی پیکربندی شده است.','Google sign-in is configured.','Google ile giriş yapılandırıldı.','تم إعداد الدخول باستخدام Google.','El acceso con Google está configurado.','L’accesso con Google è configurato.','Die Google-Anmeldung ist eingerichtet.','La connexion Google est configurée.'],
    conflict:['ایمیل یا نام کاربری قبلاً ثبت شده است.','Email or username already exists.','E-posta veya kullanıcı adı zaten kayıtlı.','البريد أو اسم المستخدم مسجل بالفعل.','El correo o usuario ya existe.','Email o nome utente già registrato.','E-Mail oder Benutzername ist bereits vorhanden.','L’e-mail ou le nom d’utilisateur existe déjà.'],
    denied:['اجازهٔ انجام این تغییر را ندارید.','You are not allowed to make this change.','Bu değişikliği yapma izniniz yok.','لا تملك إذنًا لإجراء هذا التغيير.','No tienes permiso para este cambio.','Non hai il permesso per questa modifica.','Sie dürfen diese Änderung nicht vornehmen.','Vous n’êtes pas autorisé à effectuer cette modification.'],
    validation:['فیلدها، رمز عبور و دستیارهای انتخاب‌شده را بررسی کنید.','Check the fields, password and selected assistants.','Alanları, parolayı ve seçilen asistanları kontrol edin.','تحقق من الحقول وكلمة المرور والمساعدين المختارين.','Revisa los campos, la contraseña y los asistentes seleccionados.','Controlla i campi, la password e gli assistenti selezionati.','Prüfen Sie Felder, Passwort und ausgewählte Assistenten.','Vérifiez les champs, le mot de passe et les assistants sélectionnés.']
  };
  const lang=()=>{const login=document.getElementById('login');const value=((!login?.classList.contains('hidden')&&login?.lang)||document.documentElement.lang||'en').split('-')[0];return languages.includes(value)?value:'en'};
  const t=key=>words[key]?.[languages.indexOf(lang())]||key;
  window.BeeAccountI18n={t,words,languages,lang};
  const login=document.getElementById('login'),button=document.getElementById('googleLoginBtn');
  if(!login||!button)return;
  button.hidden=false;
  const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');
  icon.setAttribute('viewBox','0 0 48 48');icon.setAttribute('aria-hidden','true');
  icon.innerHTML='<path fill="#4285f4" d="M43.6 20.5H24v8h11.3C33.7 32.7 29.2 36 24 36a12 12 0 1 1 7.9-21.1l5.7-5.7A20 20 0 1 0 44 24c0-1.3-.1-2.4-.4-3.5z"/>';
  const buttonLabel=document.createElement('span');button.replaceChildren(icon,buttonLabel);
  const title=document.createElement('h1');title.className='auth-title';
  const description=document.createElement('p');description.className='auth-description';
  button.before(title,description);
  const note=document.createElement('p');note.className='auth-provider-note';note.hidden=document.body.dataset.googleReady==='true';button.after(note);
  const username=document.getElementById('loginUser')||document.getElementById('username'),password=document.getElementById('loginPass')||document.getElementById('password');
  function label(input,key){if(!input)return;const node=document.createElement('label');node.htmlFor=input.id;node.className='auth-field-label';input.before(node);return node}
  const emailLabel=label(username,'email'),passLabel=label(password,'password');
  const params=new URLSearchParams(location.search);const error=params.get('login_error');
  const errorBox=document.getElementById('loginMsg')||document.getElementById('loginError');
  const portal=document.body.dataset.authPortal||'admin';
  const path=portal==='admin'?'/admin'+location.search:(location.pathname==='/user/settings'?'/user/settings':'/user');
  button.href='/auth/google/start?'+new URLSearchParams({portal,redirectTo:path});
  if(error){params.delete('login_error');history.replaceState(null,'',location.pathname+(params.size?'?'+params:'')+location.hash)}
  function render(){
    title.textContent=t('title');description.textContent=t('allowed');buttonLabel.textContent=t('google');note.textContent=t('not_configured');
    if(username){username.placeholder=t('email');username.setAttribute('aria-label',t('email'));emailLabel.textContent=t('email')}
    if(password){password.placeholder=t('password');password.setAttribute('aria-label',t('password'));passLabel.textContent=t('password')}
    const submit=document.getElementById('loginSubmit')||document.getElementById('loginButton');if(submit)submit.textContent=t('signin');
    if(errorBox&&error&&words[error])errorBox.textContent=t(error);
  }
  render();
  const observer=new MutationObserver(render);observer.observe(document.documentElement,{attributes:true,attributeFilter:['lang']});observer.observe(login,{attributes:true,attributeFilter:['lang']});
  // Renew persistent Admin cookies only during actual foreground activity;
  // User remains bounded by 02:00 and needs no background renewal.
  let lastActivity=Date.now();for(const event of ['pointerdown','keydown'])document.addEventListener(event,()=>{lastActivity=Date.now()},{passive:true});
  if(portal==='admin')setInterval(()=>{if(!document.hidden&&Date.now()-lastActivity<900000&&document.getElementById('app')?.classList.contains('hidden')===false)fetch('/admin/api/me',{credentials:'same-origin',headers:{'X-User-Activity':'1'}}).catch(()=>{})},900000);
})();
