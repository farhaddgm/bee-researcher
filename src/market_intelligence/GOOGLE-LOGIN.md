# ورود با گوگل و مالک حساب

## مالک
- مالک فقط حسابی است که ایمیلش برابر `MARKET_INTELLIGENCE_OWNER_EMAIL` باشد (پیش‌فرض `farhad.dgm@gmail.com`). نام کاربری و نقش ذخیره‌شده دیگر نشانهٔ مالکیت نیستند.
- migration شمارهٔ 0037 این ایمیل را به حساب مالک فعلی می‌دهد (ردیفی که نقش `owner` داشت؛ وگرنه نام کاربری `MARKET_INTELLIGENCE_ADMIN_OWNER_USERNAME`) و رمز فعلی آن را نگه می‌دارد (روش ورود `both`). به این ترتیب تا وقتی گوگل پیکربندی نشده، مالک قفل نمی‌شود.
- رمز bootstrap فقط وقتی کار می‌کند که هیچ حسابی وجود نداشته باشد (نصب اول).
- ایمیل مالک به هیچ حساب دیگری قابل تخصیص نیست و هیچ مدیری نمی‌تواند حساب مالک را تغییر دهد یا غیرفعال کند.

## صفحه‌های ورود
| مسیر | روش |
|---|---|
| `/admin` و `/user` | فقط «ورود با گوگل»، اگر پیکربندی شده باشد؛ در غیر این صورت فرم رمز عبور |
| `/admin/login-up` و `/user/login-up` | صفحهٔ بدون لینک: گوگل و رمز عبور |

پنهان بودن این آدرس‌ها لایهٔ امنیتی نیست. API ورود با رمز همچنان فعال است و محدودیت تعداد تلاش (مشترک بین هر دو پورتال) روی آن اعمال می‌شود.

## فهرست مجاز جیمیل
در صفحهٔ «امنیت» بخش «ورود با جیمیل» فقط برای مالک نمایش داده می‌شود (API: `/admin/api/owner/google-access`).
- فقط آدرس‌های ‎@gmail.com پذیرفته می‌شوند؛ نقطه‌ها، پسوند `+tag` و بزرگی و کوچکی حروف نادیده گرفته می‌شوند.
- روش ورود: «فقط جیمیل» (رمز حذف می‌شود) یا «جیمیل و رمز عبور».
- در اولین ورود، شناسهٔ حساب گوگل (`sub`) ثبت می‌شود. از آن به بعد، حساب گوگل دیگری با همان آدرس (مثلاً آدرس بازیافتی) رد می‌شود.
- با حذف دسترسی جیمیل، همهٔ نشست‌های کاربر بسته می‌شوند. اگر حساب رمز عبور نداشته باشد، غیرفعال می‌شود.

## راه‌اندازی در Google Cloud
1. در OAuth consent screen نوع External را انتخاب کنید؛ scopeهای `openid`، `email` و `profile` کافی‌اند.
2. در Credentials یک OAuth client از نوع Web application بسازید و این Redirect URI را به آن بدهید:
   `https://<دامنه>/auth/google/callback`
3. مقادیر را در `.env` قرار دهید:
```env
MARKET_INTELLIGENCE_OWNER_EMAIL=farhad.dgm@gmail.com
MARKET_INTELLIGENCE_GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
MARKET_INTELLIGENCE_GOOGLE_CLIENT_SECRET=GOCSPX-xxxx
MARKET_INTELLIGENCE_GOOGLE_REDIRECT_URI=https://<دامنه>/auth/google/callback
```
سرور باید بتواند به `oauth2.googleapis.com` درخواست بفرستد.

جریان ورود: OpenID Connect با PKCE؛ state، verifier، nonce و پورتال مقصد در یک کوکی امضاشدهٔ ۱۰ دقیقه‌ای نگه داشته می‌شوند. id_token مستقیم و از طریق TLS از endpoint توکن گوگل گرفته می‌شود (OIDC Core §3.1.3.7 بند ۶). iss، aud، exp، nonce و email_verified بررسی می‌شوند.
