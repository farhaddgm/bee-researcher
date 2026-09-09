# Market Intelligence v2.0.1

## هدف

پچ پایدارسازی بازخورد و انتشار آزمایشی پس از بک‌آفیس v2.0.0.

## تغییرات

- بازخورد برای `analysis_id` نامعتبر با خطای تفکیک‌شده رد می‌شود.
- خطاهای persistence بدون افشای secret لاگ می‌شوند.
- poller بین خطای ورودی و خطای غیرمنتظره تفکیک می‌کند.
- انتشار دستی پایدار با `message_id=27` در کانال انجام و ثبت شد.

## راستی‌آزمایی

- `/health`: سالم
- `/meta`: نسخه `2.0.1`
- تست بازخورد نامعتبر: HTTP 422 با `analysis not found for feedback`
- انتشار: `status=published`، `Publication ID=f82a27d3-0e99-4e9d-bcc2-d55c335fcf96`
