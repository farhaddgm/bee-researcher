# Bee Researcher — v3.13.0

## هدف انتشار

اجرای درخواست‌های تأییدشدهٔ منابع اجتماعی عمومی از داخل بک‌آفیس، بدون ورود
توکن توسط کاربر و بدون ذخیرهٔ credential در شیت، URL، پاسخ API یا لاگ.

## خروجی‌های اصلی

- دکمهٔ «منبع اجتماعی عمومی» در صفحهٔ رسانه اضافه شد.
- کاربر فقط پلتفرم و شناسه/لینک عمومی را وارد می‌کند؛ شناسهٔ رسانه و URL عملیاتی
  روی سرور ساخته می‌شود.
- تلگرام عمومی از `t.me/s/<handle>` خوانده می‌شود و private در این مسیر پذیرفته
  نمی‌شود.
- اینستاگرام عمومی از Meta Business Discovery با credential سروری خوانده می‌شود؛
  payload تو در تو به آیتم‌های حداقلی تبدیل می‌شود.
- X عمومی ابتدا handle را به user id تبدیل و سپس timeline را می‌خواند؛ کاربر
  نیازی به دانستن ID ندارد.
- در نبود token رسمی Meta یا X، منبع ثبت اما غیرفعال می‌شود و علت قابل‌مشاهده
  است؛ فعال‌سازی بدون credential هرگز fail-open نیست.
- کنترل‌های SSRF، حذف credential از URL و حداقل‌سازی metadata حفظ شده‌اند.

## بررسی و تست

- `git diff --check` موفق.
- `python -m unittest discover -s tests -q` موفق: ۲۵۸ تست.
- تست parser برای پاسخ Meta و جریان دومرحله‌ای X اضافه شد.
- تست UI برای مسیر `public-social-sources` اضافه شد.
- workflow CI اسکن image، تولید SBOM و verification امضای imageٔ promoted را
  انجام می‌دهد؛ health check نیز در استقرار تأیید می‌شود.

## استقرار

- image `ai-market-intelligence:3.13.0` روی production فعال است.
- `health=healthy`، پاسخ `/admin=200`، کاربر کانتینر غیر root (`10002`) و
  `readonly_rootfs=true` تأیید شد.
- لاگ راه‌اندازی پس از deploy بدون خطای جدید است.

## تنظیمات اختیاری سرور

برای Instagram و X فقط روی سرور تنظیم شود؛ هرگز در Google Sheet، فرم یا URL
قرار نگیرد:

- `MARKET_INTELLIGENCE_INSTAGRAM_SOURCE_ACCESS_TOKEN`
- `MARKET_INTELLIGENCE_X_SOURCE_BEARER_TOKEN`

تلگرام عمومی به credential نیاز ندارد. حساب‌های private در این MVP عمداً خارج
از مسیر عمومی هستند.
