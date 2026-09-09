# Bee Researcher — v3.13.1

## هدف انتشار

پیشبرد کم‌ریسک مهاجرت CSP با یک گیت regression؛ این نسخه هیچ تعامل موجودی
را حذف نمی‌کند و فقط اجازه نمی‌دهد سطح inlineهای legacy بیشتر شود.

## خروجی‌ها

- شمارنده و budget گیت برای `onclick` و `style` inline اضافه شد.
- تست fail-closed برای عبور از سقف و تست شمارش case-insensitive اضافه شد.
- baseline مهاجرت در `CSP-MIGRATION-BASELINE-v3.13.1.md` ثبت شد.
- CI پیش از ادامهٔ تست و promotion، گیت CSP را اجرا می‌کند.

## وضعیت CSP

استثناهای `script-src-attr 'unsafe-inline'` و `style-src-attr 'unsafe-inline'`
هنوز عمداً باقی هستند؛ حذف نهایی پس از مهاجرت delegated listeners، classهای
نام‌گذاری‌شده و smoke مرورگر انجام می‌شود.

## بررسی و استقرار

- `python app/market_intelligence/scripts/check_csp_inline_budget.py` موفق.
- تست کامل کانتینر با image `ai-market-intelligence:3.13.1` موفق: **۲۶۱ تست**.
- production با image `ai-market-intelligence:3.13.1` فعال و healthy است؛
  `/health` مقدار `healthy` و `/admin` کد **۲۰۰** برمی‌گرداند.
