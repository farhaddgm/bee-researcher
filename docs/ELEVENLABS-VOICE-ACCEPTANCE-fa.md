# پذیرش پیاده‌سازی صوت — نسخه 3.45.0

در ۱۱ اکتبر ۲۰۲۶، کد مرحله‌های اصلی E01 و E02 روی تصویر محلی `bee-researcher-voice:dev` با schema `0049_reader_voice` آزموده شد. ارائه‌دهنده در این آزمون‌ها مصنوعی است؛ PostgreSQL، HTTP، WebSocket، worker، میکروفن مرورگر و فایل WAV واقعی‌اند. داده یا حساب تولید استفاده نشد.

| بررسی | نتیجه محلی |
|---|---|
| آزمون‌های واحد برنامه | ۶۶۷ آزمون پاس؛ شامل رد TTD بدون پیام پایان واقعی |
| ابزار انتشار و rollback | ۴۳ آزمون پاس |
| Ruff، Mypy و Bandit با تنظیمات CI | پاس؛ Mypy بدون خطا در ۱۰۴ فایل |
| CSP inline budget و catalog ترجمه | پاس |
| resampling PCM | پاس در ۱۶، ۴۴٫۱، ۴۸ و ۹۶kHz؛ frame و tail واقعی |
| مرورگر صوت | ضبط و STT، سؤال قابل ویرایش، ارسال صریح، متن و صوت هم‌زمان، replay بدون TTS تازه، ذخیره صدای کاربر و AI، دانلود و reload یکسان، گالری خصوصی و حذف مستقل پاس |
| رابط صوت | هشت زبان × چهار اندازه صفحه و قوانین خودکار دسترس‌پذیری پاس |
| SQL صوت | ACL حتی برای Owner، بایت‌های واقعی clip/dialogue، Range، bookmark و version conflict، idempotency، lease ذخیره هنگام بستن پنجره، guard حذف متن، outbox و cascade، رقابت بودجه مشترک LLM/STT پاس |
| regression | چت خبر، حافظه پروژه، امکانات پژوهش ۶ تا ۲۰، تنظیمات کاربر، پشتیبانی، catalog/زبان‌ها و ۱۲ نمای ادمین پاس |
| startup و بازیابی | CMD واقعی با نقش محدود PostgreSQL/Redis، admission drain، readiness بعد از آزادسازی و job recovery پاس |

فرمان تکرار گیت کامل:

```sh
python3 ops/scoped-release/verify_news_chat.py --image VERIFIED_CANDIDATE
```

گیت Report و گیت‌های دیگر انتشار نیز در CI همچنان اجباری‌اند. merge و انتشار باید به commit سبز و تصویر امضاشده همان commit متصل باشند؛ این گزارش محلی جای رسید CI یا انتشار نیست.

## موارد باز برای فعال‌سازی واقعی

طبق اصلاح کاربر، ElevenLabs روی سرور تنظیم نشده است. کلید API، volume و keyring مستقل، صدای مجاز، تعرفه و capability حساب باید مطابق [راهنمای عملیات](ELEVENLABS-VOICE-OPERATIONS-fa.md) آماده و آزموده شوند. قابلیت به‌صورت پیش‌فرض خاموش است و به policy تأییدشده و کلید توقف سرور نیاز دارد.

کیفیت فارسی، قابلیت حساب/مدل و timing واقعی، latency روی شبکه تولید، zero retention حساب و دستگاه‌های واقعی Safari/iOS/Android هنوز تأیید نشده‌اند. Chromium این محیط در AudioWorklet.addModule حتی در صفحه مستقل معلق می‌ماند؛ دریافت PCM مرورگر با fallback مشترک ScriptProcessor آزموده شد. آزمون خود resampler پوشش دارد؛ اجرای Worklet روی دستگاه واقعی هنوز شرط پایلوت است. مرحله اختیاری E03 ElevenAgents/Custom LLM در این نسخه نیست.
