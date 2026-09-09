# Bee CFO parent-row flush fix v2.73.0

## تغییر اصلی

- snapshot پیش از report و report پیش از forecast به‌صورت صریح flush می‌شوند.
- ذخیره‌سازی زنجیرهٔ snapshot → report → forecast اکنون با foreign keyهای PostgreSQL سازگار است.

## اعتبارسنجی

- تست‌های Bee CFO و گیت انتشار اجرا می‌شوند.
- دو گزارش پایلوت باید بدون خطای foreign key تولید و به تلگرام تحویل شوند.
