# Bee Researcher v2.12.0

## زمان‌بندی بک‌آفیس

- زمان‌های اجرای pipeline از داخل بک‌آفیس خوانده و ویرایش می‌شوند.
- override در Redis با namespace مستقل Bee Researcher ذخیره می‌شود و بعد از restart باقی می‌ماند.
- scheduler و endpoint وضعیت از زمان‌بندی override شده استفاده می‌کنند.
- زمان‌ها با قالب `HH:MM`، حذف تکرار و ترتیب زمانی اعتبارسنجی می‌شوند.
- تغییر زمان‌بندی نیازمند نقش admin، assistant_admin یا editor است.
