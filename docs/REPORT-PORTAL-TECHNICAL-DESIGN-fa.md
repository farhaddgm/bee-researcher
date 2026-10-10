# پرتال Report — طراحی فنی و مرزهای داده

تاریخ: ۲۰۲۶-۱۰-۱۰ · وضعیت تاریخی: **طراحی قبل از توسعه**. پیاده‌سازی واقعی نسخهٔ ۳٫۴۱٫۰ در [شرح پیاده‌سازی](REPORT-PORTAL-IMPLEMENTATION-fa.md) و شواهد آزمون/انتشار در [یادداشت نسخه](RELEASE-v3.41.0-fa.md) ثبت می‌شوند.

سند محصول: [پیشنهاد Report](REPORT-PORTAL-PROPOSAL-fa.md). سناریوها: [معیارهای پذیرش](REPORT-PORTAL-ACCEPTANCE-fa.md).

## ۱. شواهد وضعیت فعلی

مبنای بررسی، checkout نسخهٔ 3.40.1 در commit `0ce8459613c9e03f79b373985a033f60fbcac069` است. بررسی کد و اسناد انجام شده، نه تست production پرتال جدید.

| مرجع در مخزن | مشاهدهٔ قابل اتکا | پیامد برای توسعهٔ آینده |
| --- | --- | --- |
| `app/auth_ui.py:8` و `app/auth_portal.js` | decorator و کنترل‌گر مشترک ورود؛ مسیرهای fetch و CSRF مخصوص Admin/User | تعمیم محدود به registry سه پرتال، نه کپی رابط یا تغییر نام چند URL |
| `app/google_auth.py:38,88` | `PORTALS` فقط Admin/User؛ redirect allowlist مخصوص هرکدام | افزودن Report به state، callback و redirect مجاز با آزمون جداسازی؛ مقدار ناشناخته fail-closed |
| `app/admin.py:1194,1247,1360` | ساخت نشست با انتخاب User از روی `nightly_reader_expiry`؛ اعتبارسنجی reader مجزا | نوع پرتال و سیاست عمر نشست باید دو پارامتر مستقل شوند |
| `app/main.py:254,731,980,994` | ساخت سند ورود، CSRF و routeهای User | پرتال تازه باید به همهٔ کنترل‌های middleware اضافه شود |
| `app/models.py:421,437,452,505` | لینک/نسخهٔ Contenter و زمینهٔ تأییدشده؛ پروفایل محلی پروژه‌ای است | شناسهٔ سراسری از شمارهٔ پروفایل محلی یا نام شرکت استنتاج نشود |
| `app/ai_relevance.py:78` | تصمیم امتیاز، اطمینان و آستانه؛ خروجی عمومی دارای `publishable` | adapter داخلی خروجی ارزیابی را بگیرد، مجوز انتشار را نگیرد |
| `app/business_context.py:56,195` | ساخت brief محدود و ارزیابی مستقل تجاری | brief همان کسب‌وکار با snapshot و اجازهٔ معتبر استفاده شود |
| `app/openai_client.py:473,537` | تحلیل ساختاریافته، زبان مشخص و `store:false` | prompt باید منشأ اظهار شرکت و عدم انتشار را بشناسد؛ سیاست ارائه‌دهنده جداست |
| `app/pipeline_service.py:1426,1966` | تحلیل صف مقاله متصل به رسانه/آستانه و مسیر انتشار | تابع صف مقاله مستقیماً برای ثبت داخلی فراخوانی نشود |
| `app/models.py:703,749` | ArticleAnalysis به مقاله وصل است؛ Publication به تحلیل وصل و قابل ارسال است | گزارش داخلی در مدل Publication قرار نگیرد |
| `app/news_chat/context.py:19,47` | زمینه و پرامپت فقط گزارش منتشرشده | Report به چت عمومی وصل نشود؛ هر چت آینده ACL خصوصی می‌خواهد |

همهٔ مسیرهای `app/…` در این جدول زیر `src/market_intelligence/` هستند. شماره‌ها به commit مبنا تعلق دارند و با توسعه جابه‌جا می‌شوند.

## ۲. قیود غیرقابل دورزدن

- گزارش و تحلیل داخلی همیشه `origin=internal_report` و `visibility=private` داشته باشند؛ این مقادیر را سرور تعیین کند.
- Report در `SourceItem`، `NormalizedArticle`، `ArticleAnalysis` یا `Publication` عمومی با شناسهٔ ساختگی ثبت نشود. اصل‌های خصوصی و خروجی‌های آن‌ها در جدول‌های اختصاصی باشند.
- هیچ job عمومی، export، جست‌وجو، feed، چت، گزارش تجمیعی یا webhook با query عمومی به دادهٔ Report دسترسی نداشته باشد.
- ثبت، خواندن، نسخه‌سازی، تحلیل، حذف و فهرست همگی به grant فعال بیزینس و پروژه کنترل شوند؛ session login کافی نیست.
- کاربر/Owner، `business_id`، نقش، سطح دسترسی یا مقصد انتشار را از فیلد قابل ویرایش فرم به سرور تحمیل نکند.
- متن خبر و دادهٔ Contenter «داده»اند، نه دستور. تحلیل هیچ ابزار publish، web-search، ایمیل، فایل یا shell در اختیار مدل قرار ندهد.
- پایین‌بودن امتیاز، نبود کسب‌وکار در تحلیل، خطای مدل و فقدان شواهد هرکدام معنای مستقل و قابل نمایش داشته باشند.
- نسخهٔ ثبت‌شده و تحلیل آن تغییرناپذیر باشند؛ اصلاح و تحلیل مجدد رکورد جدید بسازند.
- دادهٔ داخلی به Contenter نوشته نشود؛ اتصال فعلی فقط brief مجاز را بخواند. دادهٔ محصولات هم‌سرور و Bee CFO دست‌نخورده بماند.

## ۳. ساختار پیشنهادی ماژول

یک بستهٔ مستقل مانند `app/report_portal/` برای API، policy، مدل‌های درخواست، سرویس ثبت، تحلیل و UI؛ نام‌ها در توسعه تثبیت شوند. assets مستقل با design tokenها، لوگو، وزیرمتن و اجزای مشترک User بارگذاری شوند؛ لایهٔ تزریقی جدید در فایل بزرگ Admin ساخته نشود.

ورود و شناسایی حساب می‌توانند مشترک بمانند، اما resolver نشست `current_reporter` و کنترل دسترسی محتوا اختصاصی باشند. اجزای بدون I/O مانند ارزیابی آستانه و اعتبارسنجی شواهد قابل اشتراک‌اند. orchestrator ثبت داخلی، بودجه، storage و صف انتشار نباید مشترک شوند.

استخراج رابط تحلیل مشترک باید قرارداد نوع‌دار و تست regression داشته باشد؛ تغییر رفتار پروژه‌های فعلی یا افزایش scope پرامپت عمومی نتیجهٔ جانبی قابل قبول نیست.

## ۴. هویت، نشست و OAuth

Registry پیشنهادی شامل `admin`, `user`, `report` و برای هرکدام base path، cookie، CSRF cookie، allowlist redirect و policy نشست باشد. رشتهٔ دلخواه کاربر یا نوع ناشناخته به Admin fallback نکند.

کوکی‌های پیشنهادی Report: `research_bee_report_session` و `research_bee_report_csrf` با path `/report`، Secure و SameSite متناسب جریان OAuth؛ نشست HttpOnly و hash آن در سرور. path کوکی فقط کاهش تداخل است، نه اثبات مجوز. توکن report در resolver admin/user و برعکس رد شود.

callback موجود Google در `/auth/google/callback` قابل استفاده با state امضاشدهٔ حامل `portal=report` است. PKCE، nonce، ایمیل تأییدشده، subject، rate limit و binding هویت حفظ شوند. امنیت ورود رمزی و login-CSRF نیز برای Report برقرار باشد. ورود هم‌زمان در چند tab و تطبیق state/portal آزموده شود.

پیشنهاد cutoff همان ۰۲:۰۰ User در timezone سرویس است؛ نوع پرتال نباید همچنان از «شبانه بودن عمر» نتیجه گرفته شود. تغییر grants، بیزینس، نقش یا وضعیت، نشست‌های مربوط را باطل و اعتبار درخواست‌های در جریان را دوباره بررسی کند. اتمام نشست مرورگر لزوماً job قبلاً مجاز را لغو نمی‌کند؛ خروجی فقط به نشست معتبر ارائه شود. لغو grant یا consent بیزینس باید **ارسال بعدی به provider** را متوقف کند.

از آنجا که فعلاً Gmail/Googlemail کنترل می‌شود، ایمیل سازمانی خارج از این دامنه دامنهٔ نسخهٔ اول نیست. توسعهٔ آن نیازمند قرارداد محصول و آزمون ورود مستقل است، نه برداشتن بی‌اعلام محدودیت همهٔ پرتال‌ها.

## ۵. بیزینس و مجوزها

یک شناسهٔ داخلی پایدار برای بیزینسِ Report لازم است. آن شناسه به مرجع معتبر `(source_system, source_instance, external_business_id)` برای Contenter یا `(assistant_id, local_profile_id)` برای بیزینس محلی متصل شود. شمارهٔ محلی پروفایل و نام شرکت کلید چندبیزینسی نیستند. هیچ عضویت Contenter از روی کاتالوگ کامل برای حساب Researcher استنتاج نشود.

مجوز پیشنهادی: user، report-business، نقش و وضعیت، زمان ایجاد/لغو و actor. project-binding مستقل مشخص کند همین بیزینس برای کدام assistant تحلیل می‌شود؛ تغییر generation لینک نباید تاریخچه را منتقل کند.

Policy خواندن یک گزارش: حساب فعال + نشست Report معتبر + grant فعال همان بیزینس + پروژهٔ مجاز + مالک گزارش یا نقش مدیر بیزینس. حساب مدیر پروژهٔ عمومی به‌تنهایی مجاز نیست. Owner می‌تواند grantها را اداره کند، ولی خواندن متن داخلی به grant محتوایی نیاز داشته باشد و ایجاد آن ممیزی و به مدیر بیزینس اطلاع داده شود.

مهم: این طرح یک کنترل مجوز در نرم‌افزار است، نه محرمانگی رمزنگارانه در برابر مالک سرور. دسترسی اضطراری عملیات باید محدود، علت‌دار و ممیزی‌شده باشد. اعطای پنهانی مجوز به خود در UI نباید عادی‌سازی شود.

Queryهای list/count/search/detail همگی scope مشابه داشته باشند؛ جزئیات و وجود شناسهٔ غیرمجاز با پاسخ کنترل‌شدهٔ یکسان افشا نشوند. cache و کلید idempotency نیز scope بیزینس/کاربر داشته باشند.

## ۶. مدل دادهٔ پیشنهادی

نام‌های زیر قرارداد طراحی‌اند، نه جدول ایجادشده یا شمارهٔ migration رزروشده:

| موجودیت | اطلاعات اصلی |
| --- | --- |
| ReportBusiness | مرجع پایدار بیزینس، سیاست AI/نگهداری و وضعیت؛ بدون کپی کامل Contenter |
| ReportBusinessGrant | کاربر، بیزینس، نقش، grant/revoke و actor |
| ReportProjectBinding | بیزینس، دستیار، پیوند معتبر و وضعیت استفاده برای Report |
| InternalReport | شناسهٔ opaque، بیزینس، پروژه، author واقعی، نسخهٔ جاری، visibility و چرخهٔ سند |
| InternalReportVersion | متن و تیتر، byline، برچسب‌ها، زبان، تاریخ وقوع، classification، هش کامل متن و parent version |
| InternalReportAnalysis | report-version، خروجی و شواهد، Topic scores، business assessment، مدل، provenance، کیفیت و هزینه |
| InternalReportJob | صف، تلاش، lease/heartbeat، next retry، cancellation و کد خطای امن |
| ReportAudit/Outbox | actor/شناسه/عمل/نتیجه و event هماهنگ با transaction؛ بدون متن خبر |

گزارش‌های ثبت‌شده از حذف account/project/binding ناگهانی cascade محتوایی نداشته باشند. حذف نهایی از مسیر policy retention و مجوز انجام شود. حذف کسب‌وکار یا قطع دسترسی تحلیل جدید را متوقف کند و تاریخچه به کسب‌وکار جایگزین منتقل نشود.

چرخهٔ سند: `draft → submitted → archived`؛ اصلاح از submitted یک draft/version تازه ایجاد می‌کند. چرخهٔ job جدا: `queued → running → succeeded | needs_input | failed | cancelled`. نتیجهٔ ارتباط نیز جدا: `relevant | review | low_relevance | unknown`. هیچ وضعیت `published` برای این موجودیت‌ها تعریف نشود.

## ۷. قراردادهای API پیشنهادی

تمام endpointهای این بخش فقط **طراحی آینده** هستند:

- `GET /report`: پوسته و ورود مشترک، سپس فرم پیش‌فرض.
- `GET /report/reports` و `GET /report/reports/{id}`: فهرست و جزئیات دارای احراز هویت؛ مسیر URL شامل تیتر/متن نباشد.
- `GET /report/api/me`: هویت، grantهای محدود و وضعیت نشست/CSRF.
- `GET /report/api/contexts`: فقط بیزینس/پروژه/موضوع مجاز و policy آماده‌سازی؛ نه کاتالوگ سراسری Contenter.
- `POST /report/api/drafts` و `PATCH /report/api/drafts/{id}`: ذخیرهٔ پیش‌نویس با revision/If-Match؛ بدون فراخوانی AI.
- `POST /report/api/drafts/{id}/submit`: تأیید نسخه/سیاست، idempotency key، ثبت نهایی و enqueue؛ پاسخ ۲۰۲ با report/job IDs.
- `GET /report/api/reports` و `GET /report/api/reports/{id}`: metadata محدود و متن فقط پس از object authorization.
- `GET /report/api/reports/{id}/analyses/{analysis_id}`: نسخهٔ نتیجه/وضعیت و شواهد همان گزارش.
- `POST /report/api/reports/{id}/revisions`: draft جدید با parent؛ اصل بازنویسی نشود.
- `POST /report/api/reports/{id}/reanalyze`: فقط کاربر مجاز با سهمیه و نسخه/consent معتبر؛ تحلیل تازه، نه تغییر امتیاز دلخواه.
- `DELETE /report/api/reports/{id}`: درخواست حذف با policy و تأیید؛ مجوز جدا و نتیجهٔ روشن.

grant-management زیر بخش مدیریت حساب Admin با مجوز Owner و CSRF انجام شود، نه توسط فرم ثبت خبر. دکمهٔ عمومی‌کردن، اشتراک anonymous، ارسال Telegram یا download عمومی وجود نداشته باشد.

خطاها: ۴۰۱ نشست، ۴۰۳ مجوز/consent، ۴۰۴ شیء در scope پیدا نشد، ۴۰۹ revision یا درخواست متعارض، ۴۱۳ اندازهٔ داده، ۴۲۲ فیلد، ۴۲۹ سهمیه، ۵۰۳ dependency. کدهای ماشینی محلی‌سازی شوند؛ پاسخ خام provider/stacktrace/payload برنگردد.

## ۸. تحلیل خصوصی و reuse صحیح

قبل از provider call: دسترسی، business binding، consent، classification، موضوع فعال، بودجه، طول متن و آماده‌بودن مدل کنترل شوند. reserve مصرف و job ID قبل از I/O، و outbox هم‌تراکنش با ثبت نهایی باشد. درخواست HTTP فرم منتظر چند دقیقه تحلیل نماند.

Report از gate انتشار عمومی عبور نمی‌کند. همهٔ گزارش‌های ثبت‌شدهٔ معتبر، از جمله موارد کم‌ارتباط، خلاصه/تحلیل بگیرند. نبود Topic فعال به‌جای امتیاز ساختگی مانع submit باشد؛ نبود brief تأییدشده خروجی تجاری را «در دسترس نیست» کند، ولی تحلیل موضوعی مجاز را متوقف نکند.

امتیاز و تصمیم مطابق `relevance_decision` و سیاست Topic/کف پروژه محاسبه شود؛ آستانه به prompt برای تنظیم دلخواه score داده نشود. جهت پایین/بالا بودن امتیاز و confidence به کاربر توضیح داده شود. برچسب آزاد کاربر فقط annotation است، نه Topic رسمی یا شاهد صحت.

business score مستقل از Topic score باقی بماند. وقتی brief معتبر موجود است، از همان روش topics/contextual/focused تأییدشدهٔ پروژه استفاده شود؛ هیچ brief کامل خام یا کسب‌وکار دیگر در prompt وارد نشود.

اجازهٔ استفاده از brief در تحلیل خصوصی از اجازهٔ افشای حقایق در گزارش عمومی جدا باشد. برای رساندن دادهٔ مجاز به analyzer داخلی، گزینهٔ `disclose_facts` یا سیاست افشای پروژهٔ عمومی روشن نشود؛ accessor خصوصی با consent Report و scope همان بیزینس لازم است.

پرومپت داخلی منشأ «اظهار مستقیم شرکت، منتشرنشده، فاقد راستی‌آزمایی بیرونی» را صریح بیان کند. `published_at` ساختگی یا source_url عمومی لازم نیست. ارجاع به شناسهٔ بند/نسخهٔ خبر داخلی باشد، نه URL حدسی رسانه. شواهد نقل‌شده در سرور به متن همان نسخه و ادعاهای مجاز وصل شوند.

خروجی: همان فیلدهای تحلیل فعلی به‌علاوه provenance منشأ، evidence class، limitation و سؤال تکمیلی؛ schema، دامنهٔ عدد، زبان خروجی و کیفیت معنایی جدا بررسی شوند. مدل هیچ ابزاری برای انتشار ندارد؛ prompt امن به‌تنهایی تضمین دفاع از تزریق نیست.

حد پیشنهادی متن در فرم ۲۰٬۰۰۰ نویسه است، اما `analysis_max_input_chars` هر پروژه ممکن است کمتر باشد. effective limit پیش از ارسال نشان داده شود؛ هیچ trim پنهانی یا نتیجهٔ کامل برای متن ناقص مجاز نیست. متن بیش از ظرفیت یا رد شود یا بعد از تصمیم آینده با chunking دارای coverage تحلیل شود.

نسخهٔ مدل، هش کامل متن، Topic snapshot/threshold، brief snapshot/generation، زبان، prompt revision و consent policy در provenance ثبت شوند. تغییر semantic داده نتیجهٔ تازه لازم دارد؛ تغییر فقط threshold می‌تواند تصمیم را با score معتبر بازحساب کند. تحلیل تاریخی با برچسب نسخه حفظ شود.

## ۹. ایزوله‌سازی، حریم خصوصی و نگهداری

تخصیص جدول‌های جدا نشت را ناممکن نمی‌کند؛ عدم import در publisher، نبود foreign key به Publication، اجازهٔ outbound محدود worker و آزمون همهٔ egressها دفاع‌های مکمل‌اند. هر قابلیت آیندهٔ تبدیل عمومی به نسخهٔ مستقل و explicit approval نیاز دارد.

ورودی/خروجی و متادیتای حساس Report باید با رمزنگاری استاندارد مدیریت‌شده، کلید حفاظت‌شده بیرون از repo و کنترل دسترسی storage نگهداری شوند؛ جزئیات key rotation، رمزنگاری بکاپ و مجوز DB در توسعه ارزیابی و تست شوند. رمزنگاری در حالت ذخیره، end-to-end در برابر سرویس تحلیل نیست؛ worker متن مجاز را برای تحلیل می‌خواند.

`Cache-Control: no-store`، عدم cache در service worker/CDN، noindex/nofollow و حذف از sitemap برای صفحه/API. noindex کنترل دسترسی نیست. URL/share token، logs، crash report، replay analytics و اعلان‌ها نباید تیتر/بدنه/نام اشخاص یا پاسخ AI را حمل کنند. query جست‌وجوی خصوصی به لاگ دسترسی راه پیدا نکند؛ قرارداد search مطابق این قید طراحی شود.

گزارش‌های private نباید وارد cache جهانی، embedding/RAG عمومی، sheet sync، chat history User یا اسناد عمومی مخزن شوند. test fixtures فقط ساختگی باشند. هم‌شکل بودن محتوای دو شرکت نباید با dedup جهانی به یکی نشان داده شود.

پالیسی provider مستقل از flag `store:false` است. قبل از call باید مجوز بیزینس برای classification/model/provider جاری معتبر باشد؛ در تغییر سیاست consent تازه یا توقف امن لازم است. نبود تأیید ZDR با label «نگهداری صفر» پوشانده نشود. خبر بسیار محرمانه در این نسخه به provider بیرونی نرود؛ local analysis هنوز پیاده نشده است.

retention پیشنهادی draft ۳۰ روز و report/result ۹۰ روز است؛ زمان ایجاد/آخرین submit نسخه مبنای دقیق و expiry ثابت داشته باشند. حذف کامل شامل نسخه‌ها، خروجی، cache، job payload و backup lifecycle شود. دادهٔ خصوصی در queue payload فقط reference باشد، نه متن تکرارشده.

بکاپ می‌تواند متن حذف‌شدهٔ قبلی داشته باشد؛ registry حذف/expiry و replay پس از restore قبل از بازکردن سرویس ضروری است. پنجرهٔ واقعی حذف بکاپ، legal hold و مسئول تأیید policy پیش از فعال‌سازی مشخص شوند؛ ادعای حقوقی رعایت همهٔ قوانین داده بدون بررسی مستقل نشود.

## ۱۰. پایداری و محدودسازی مصرف

- lease، heartbeat و reaper برای job رهاشده؛ وضعیت running نامحدود نماند.
- idempotency submit و analysis با scope بیزینس/نسخه؛ دوبار کلیک نتیجهٔ واحد بدهد.
- بودجه و سقف روزانهٔ مستقل، قیمت از کاتالوگ معتبر فعلی و reserve/reconcile؛ retry رایگان فرض نشود.
- provider timeout پاسخ نامعلوم ممکن است هزینه داشته باشد؛ تلاش مجدد بی‌نهایت یا retry فوری request مبهم مجاز نیست.
- semaphore محدود و fairness؛ تحلیل داخلی خزش/انتشار موجود را گرسنه نکند.
- گزارش آماری فقط شمارش، زمان، مصرف و error code؛ بدون محتوا و امکان infer بیزینس دیگر برای کاربر.
- وضعیت صف با polling محدود و backoff، بدون تمدید خودکار cutoff نشست؛ درصد یا ETA ساختگی نباشد.

## ۱۱. برنامهٔ توسعه و انتشار پیشنهادی

feature flag پیش‌فرض خاموش. migration افزایشی فقط در schema Researcher پس از تأیید و backup؛ عدم پاک‌کردن داده یا نشست‌های همهٔ محصولات. نوع نشست تازه را بدون بازتفسیر توکن قدیمی اضافه کنید.

ترتیب کار: policy و grant ← storage/versions/consent ← auth registry ← فرم/لیست ← orchestration خصوصی و reuse تحلیل ← privacy/retention/monitoring ← unit/API/browser/egress tests ← انتشار محدود.

CI به نتیجهٔ واقعی E2E نیاز داشته باشد؛ skipped از نبود account/URL موفقیت پذیرش نیست. نمونهٔ private marker در محیط ایزوله ثبت و نبودش در همهٔ کانال‌های عمومی کنترل شود. runtime و بار صف عمومی پیش و پس از توسعه مقایسه شوند.

در انتشار آینده فقط Researcher تغییر کند؛ Contenter، Consultant و Bee CFO restart یا migrate نشوند. برای rollback کد، جدول افزوده حفظ و feature flag خاموش شود؛ downgrade مخرب روش بازگشت نیست.

## ۱۲. منابع تصمیم‌های امنیتی

دسترسی پیش‌فرض بسته و object authorization از [OWASP Authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)، جداسازی داده/دستور و محدودسازی ابزارها از [OWASP LLM Prompt Injection](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)، و الزام بررسی مستقل نگهداری provider از [OpenAI Data Controls](https://developers.openai.com/api/docs/guides/your-data) اقتباس شده‌اند. این‌ها منابع طراحی‌اند، نه گواهی امنیت یا تضمین محرمانگی مطلق.
