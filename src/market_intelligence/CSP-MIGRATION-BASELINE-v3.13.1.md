# CSP migration baseline — v3.13.1

این نسخه یک گیت پایش اضافه می‌کند تا سطح فعلیِ سازگاری CSP در بک‌آفیس
بدتر نشود. تا زمانی که مهاجرت مرحله‌ای کامل نشده، حذف ناگهانی استثناهای
`unsafe-inline` می‌تواند کنترل‌های قدیمی را از کار بیندازد.

## baseline ثبت‌شده

- `onclick` inline: **۱۳۲** مورد (سقف مجاز فعلی: ۱۳۲)
- `style` inline: **۶۲** مورد (سقف مجاز فعلی: ۶۲)
- مسیر بررسی: `app/market_intelligence/app/admin_ui.py`
- فرمان: `python app/market_intelligence/scripts/check_csp_inline_budget.py`

گیت فقط افزایش را مسدود می‌کند؛ مرحلهٔ بعدی باید این اعداد را با جایگزینی
listenerهای delegated و classهای نام‌گذاری‌شده کاهش دهد. پس از smoke مرورگر و
گزارش Report-Only، سقف‌ها باید پایین آورده شوند و در نهایت استثناهای CSP حذف
شوند.
