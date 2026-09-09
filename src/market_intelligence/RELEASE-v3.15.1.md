# Bee Researcher — v3.15.1

## امنیت CSP — مرحلهٔ پایش

- سیاست سخت‌گیرانهٔ CSP، بدون `script-src-attr` و `style-src-attr`، در کنار
  سیاست سازگاری فعلی با header مستقل `Content-Security-Policy-Report-Only`
  ارسال می‌شود.
- گزارش‌های مرورگر به مسیر same-origin زیر می‌رسند و نیازی به نشست کاربر ندارند:
  `/admin/api/security/csp-report`.
- endpoint گزارش فقط ۲۰ گزارش و ۶۴ کیلوبایت payload را می‌پذیرد، فیلدهای
  محدود را نگه می‌دارد و مقدارهای حساس را پیش از log کردن redact می‌کند.
- سیاست enforce فعلی عمداً استثناهای inline را نگه می‌دارد تا قبل از مهاجرت
  کامل listener/class، تعاملات قدیمی از کار نیفتند.

## تست و انتشار

- تست کامل: **۲۷۳ تست موفق**.
- بررسی ایستایی Python و CSP inline budget موفق.
- health production: `healthy`؛ PostgreSQL و Redis سالم.
- `/admin` و endpoint گزارش CSP روی دامنهٔ عمومی بررسی شدند.

## گام بعدی MI-208

گزارش‌های Report-Only باید در مرورگر واقعی مرور شوند؛ سپس inline eventها به
listenerهای delegated و inline styleها به class/token منتقل و بعد از smoke کامل،
دو compatibility exception از سیاست enforce حذف می‌شوند.
