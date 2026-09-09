# Bee Researcher v2.11.3

## queue/cache isolation

- قفل pipeline اکنون کلید Redis معتبر و قابل parse دارد.
- کلید قفل برای هر workspace جداست و دو اجرای workspace متفاوت یکدیگر را block نمی‌کنند.
- تست رگرسیون برای تفاوت کلیدها و نبود separator نامعتبر اضافه شد.
