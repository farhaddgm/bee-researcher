# Bee CFO report persistence fix v2.72.0

## تغییر اصلی

- پیش از درج forecastها، رکورد report اصلی flush می‌شود تا وابستگی foreign key در PostgreSQL رعایت شود.
- تولید گزارش Bee CFO اکنون می‌تواند snapshot، report و سه forecast را به‌صورت اتمیک ذخیره کند و سپس وارد delivery ledger شود.

## اعتبارسنجی

- تست‌های Bee CFO و گیت انتشار اجرا می‌شوند.
- دو اجرای on-demand پایلوت باید بدون خطای foreign key تولید و به تلگرام تحویل شوند.
