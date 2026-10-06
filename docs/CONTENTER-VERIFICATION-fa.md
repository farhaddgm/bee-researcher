# نتیجهٔ توسعه و آزمون اتصال Contenter

تاریخ: ۲۰۲۶-۱۰-۰۶

## نتیجهٔ محصول

کسب‌وکار در Contenter ایجاد/ویرایش می‌شود. در صفحهٔ کسب‌وکار Researcher، مالک یا مدیر دارای اجازهٔ نوشتن پروژه، پروفایل موجود را انتخاب و به همان پروژه متصل می‌کند. انتخاب برای تمام کسب‌وکارهای فعلی و آینده با `RESEARCHER_BUSINESS_ACCESS=all` پویاست؛ نیاز به ویرایش فهرست شناسه‌ها یا restart برای کسب‌وکار تازه ندارد. چند پروژه می‌توانند به یک کسب‌وکار متصل شوند؛ پروژهٔ بدون کسب‌وکار هم معتبر است.

در این مرحله اتصال، مشاهده، همگام‌سازی و نگهداری نسخه‌ها پیاده‌سازی شده‌اند. **گام ۴ اجرا نشده است:** پروفایل بیرونی هنوز ورودی امتیازدهی/تحلیل AI، ترجمه یا انتشار نیست. تنظیمات و پروفایل‌های محلی موجود تغییر نکرده‌اند. هیچ کسب‌وکار واقعی به هیچ پروژه‌ای خودکار وصل نشده است.

## آزمون‌های انجام‌شده

- Researcher: ۴۹۰ تست واحد/رگرسیون موفق، شامل ۱۵ تست ماژول جدید.
- بررسی نوع کل اپ Researcher: بدون خطا در ۵۵ فایل.
- Contenter API: ۱۹۴ تست موفق در ۱۶ فایل، شامل آزمون‌های Docoo و مصرف‌کنندهٔ مستقل Researcher؛ typecheck و build موفق.
- PostgreSQL واقعیِ ایزوله: migration از ابتدا تا 0041؛ اتصال/همگام‌سازی، عدم ساخت نسخهٔ تکراری، ایجاد نسخهٔ جدید با تغییر محتوا، sync هم‌زمان، قطعی موقت، لغو دسترسی، جداکردن/تعویض پیوند و پاسخ دیرهنگام پس از unlink موفق.
- اتصال واقعی HTTPS میان دو سرویس آزمایشی: جدایی توکن Docoo/Researcher، فهرست و export معتبر، مشاهدهٔ کسب‌وکار ساخته‌شده پس از راه‌اندازی بدون restart، سالم‌ماندن Docoo.
- Playwright با مرورگر واقعی: ورود، جست‌وجو، اتصال، مشاهده، sync، unlink، جدایی پروژه‌ها، نشست‌های واقعی viewer/editor، منع دسترسی به پروژهٔ دیگر و تنظیمات مالک؛ موفق.
- پروفایل در هشت زبان و چهار عرض ۱۴۴۰، ۹۰۰، ۳۹۰ و ۳۲۰ پیکسل؛ متن محلی رابط، عدم خروج مودال از صفحه، Escape و نگه‌داشتن focus، عدم اجرای HTML ذخیره‌شده؛ موفق.
- پاسخ ناسازگار/ناقص، redirect، timeout، JSON خراب و بیش از ۶ مگابایت، توکن نامعتبر، حذف/بایگانی و انقضای cache؛ fail-safe.

## مرز محیط آزمایش

دو API، PostgreSQL، Redis و TLS proxy آزمایشی در شبکهٔ Docker داخلیِ بدون اینترنت اجرا شدند. حساب‌ها، پروفایل‌ها و رمزها مصنوعی بودند. هیچ درخواست AI، خزش یا انتشار تلگرام انجام نشد. تنظیم کوکی HTTP فقط برای محیط `test` تغییر کرد؛ production همچنان HTTPS/کوکی امن را الزامی می‌کند. repo اصلی Contenter، working tree قدیمی و تغییرات قبلی دیگر پروژه‌ها دست‌نخورده باقی ماندند.

این گزارش آزمون توسعه است، **نه ادعای انتشار روی production**. کد اتصال در شاخه‌های مستقل `codex/contenter-business-integration` و `codex/researcher-business-integration` نگهداری می‌شود. فعال‌سازی نسخهٔ زنده باید با دو تصویر ساخته‌شده از همین تغییرات، اعتبارنامهٔ تازه و migration افزایشی انجام شود؛ API Docoo و سایر سرویس‌ها نباید restart یا تغییر کنند.

## راه‌اندازی نسخهٔ زنده برای مسئول انتشار

۱. از DB/schema Researcher بکاپ بگیرید؛ Contenter برای این تغییر migration ندارد.

۲. تصویر API Contenter را از شاخهٔ اتصال بسازید. رمز تصادفی مستقل مصرف‌کننده را در محل محرمانهٔ تنظیمات سرویس قرار دهید؛ با توکن Docoo یکسان نباشد. فقط API Contenter نیاز به env جدید دارد، نه worker، web یا Docoo:

```text
RESEARCHER_INTEGRATION_TOKEN=<independent secret, at least 32 characters>
RESEARCHER_BUSINESS_ACCESS=all
```

۳. در Researcher نشانی واقعی HTTPS دو سرویس و همان رمز را تنظیم کنید؛ پیش‌فرض sync هر ۱۵ دقیقه و اعتبار cache تا ۲۴ ساعت است:

```text
MARKET_INTELLIGENCE_CONTENTER_API_URL=https://<contenter-host>/api
MARKET_INTELLIGENCE_CONTENTER_WEB_URL=https://<contenter-host>
MARKET_INTELLIGENCE_CONTENTER_TOKEN=<same independent secret>
MARKET_INTELLIGENCE_CONTENTER_SYNC_SECONDS=900
MARKET_INTELLIGENCE_CONTENTER_CACHE_MAX_AGE_SECONDS=86400
```

۴. فقط نسخهٔ API Contenter و سرویس Researcher را به‌روزرسانی کنید. migration 0041 فقط دو جدول جدید در schema Researcher می‌سازد. بررسی سلامت و آزمون اتصال در Settings و سپس انتخاب کسب‌وکار در صفحهٔ کسب‌وکار انجام شود. secret را در UI، چت، خروجی فرمان، Git یا فایل گزارش ننویسید.

۵. rollback کد/تصویر اتصال‌ها را غیرفعال می‌کند، اما جدول‌های افزوده را حفظ کنید تا نسخه‌ها پاک نشوند. downgrade مخرب migration عمداً مسدود است. برای بازگشت، نسخهٔ سالم قبلی را با جدول‌های افزوده اجرا کنید؛ جداولِ استفاده‌نشده برای کد قبلی مشکلی ایجاد نمی‌کنند.

## بازاجرای آزمون‌ها

مسیر کد Researcher: `src/market_intelligence`.

```sh
python -m unittest discover -s tests -q
mypy --ignore-missing-imports app
python scripts/verify_contenter_sql.py
node scripts/verify_contenter_browser.mjs
```

دو آزمون آخر فقط محیط ایزوله می‌پذیرند: `MARKET_INTELLIGENCE_ENVIRONMENT=test`، DB `assistant_test`، حساب مصنوعی owner، بدون AI و Telegram پیکربندی‌شده. برای تست مرورگر `BEE_ADMIN_URL` و اعتبارنامهٔ مصنوعی ورود لازم است؛ `biz1` با متن آزمایشی HTML و `biz2` ساخته‌شده بعد از راه‌اندازی، در Contenter آزمایشی موجود باشند. اگر نسخهٔ Playwright و Chromium تصویر متفاوت باشد، `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` به مسیر مرورگر همان تصویر اشاره کند. عدم وجود پیش‌نیاز باعث شکست تست می‌شود، نه skip موفق.

در Contenter:

```sh
npm run typecheck -w @contenter/api
npm run test -w @contenter/api
npm run build -w @contenter/api
```
