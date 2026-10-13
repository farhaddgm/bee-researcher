# طرح فنی و قراردادهای پیشنهادی

نسخهٔ طراحی: ۱٫۰ · مبنا: checkout `7774065f5406751aa610dc20b4919e66d800a242`، نسخهٔ برنامه ۳٫۵۰٫۰

تمام جدول‌ها، endpointها و payloadهای جدید این سند **پیشنهادی‌اند؛ در برنامهٔ فعلی وجود ندارند**. قرارداد نهایی باید در پیاده‌سازی، OpenAPI و آزمون contract تثبیت شود. مسیرهای «موجود» جدا مشخص شده‌اند.

## ۱. تطبیق با کد موجود

| جزء موجود | استفادهٔ پیشنهادی | مرز تغییر |
| --- | --- | --- |
| `app/news_chat/context.py` | متن قابل مشاهده، قطعات استناد و prompt پایه | خروجی داخلی pipeline و اصل مقاله خودکار وارد نشوند |
| `app/news_chat/schemas.py` | `ResearchStart`، `Question` و schema سخت‌گیرانه | حداکثر پنج `source_ids` با احتساب مرکز؛ clients قدیمی معتبر بمانند |
| `app/news_chat/service.py` | کنترل مجوز، generation، worker، هزینه، توقف، حذف | مسیر پولی دوم یا lock process-local ساخته نشود |
| `app/news_chat/models.py` | `ChatConversation.context` و `ChatGeneration` | لنز و نتیجه به گفتگوی فعلی متصل، نه conversation موازی |
| `app/news_chat/api.py` | نشست Reader، SSE، memory و `owner()` | مدیریت با cookie ادمین و Owner واقعی؛ اجرا با نشست User |
| `app/reader_research/service.py` | `selected_context/validate_context` | منابع مجاز همان پروژه و hash منابع پیش از اجرا |
| `app/reader_research/api.py` | الگوی feed با publication و تاریخ مقاله | discovery تازه نباید روی صفحهٔ بارگذاری‌شدهٔ مرورگر متکی باشد |
| `app/reader_tools` | هشدار اصلاح/تغییر گزارش و شواهد نسخه‌دار | گزارش اصلاح‌شده یا حافظهٔ وابسته بدون بازاعتبارسنجی استفاده نشود |
| `app/news_voice` | متن به صوت و ورودی صوتی فعلی | لنز اجازهٔ تازه به صوت/ارائه‌دهنده/حافظه نمی‌دهد |
| `app/answer_length.py` و Reader defaults | طول پاسخ و مدل فعلی | تنظیم مالک لنز، تنظیم مدل یا pipeline را بازنویسی نمی‌کند |
| ledger و migration `0051_token_quotas` | سقف‌های کاربر/پروژه/سرویس و تسویه | پیش‌نمایش و تحلیل از همان مصرف می‌گذرند |

مبنای گفتگو متن گزارش منتشرشدهٔ تولیدشده با AI است، نه اصل کامل و مستقلاً تأییدشدهٔ خبر. `context_for` در مبنای فعلی حداکثر ۱۶۰۰۰ نویسه را با اعلام نقص زمینه آماده می‌کند؛ محدودیت مدل و مجموع چند گزارش مستقل‌اند.

`selected_context` الزام می‌کند خبر مرکزی در انتخاب‌ها باشد و منابع به همان پروژه تعلق داشته باشند. نسخهٔ جدید این کنترل را تضعیف نمی‌کند. `owner()` فعلی با `admin.is_owner` بررسی می‌کند؛ نقش موسوم به مدیر کل اگر Owner محسوب نشود، اختیار مدیریت این ویژگی را ندارد.

## ۲. ساختار ماژول پیشنهادی

فایل‌های جدید زیر `src/market_intelligence/app/analysis_lenses/`:

- `schemas.py`: شناسنامه، نسخه، انتخاب تحلیل، خروجی، خطاها.
- `models.py`: لنز، نسخه، policy سرویس، تلاش‌های پیش‌نمایش و snapshot پیشنهادها.
- `catalog.py`: چهار قالب اولیهٔ نسخه‌دار؛ seed صریح و idempotent.
- `service.py`: draft/validation/publication/revocation و مجوزهای مدیریت.
- `compiler.py`: ساخت prompt محدود از تعریف معتبر زیر قواعد پایه.
- `discovery.py`: پیشنهاد محدود و قابل توضیح از گزارش‌های منتشرشده.
- `context.py`: metadata ثابت تحلیل، fingerprint و بازاعتبارسنجی.
- `results.py`: validation ساختاری، ارجاع‌ها و نگاشت امن به متن گفتگو.
- `api.py`: endpointهای Owner و Reader و whitelist دارایی‌ها.
- `admin.js/admin.css` و `reader.js/reader.css`: رابط محدود به صفحهٔ درست، cleanup کامل.
- `i18n.js`: UX writing هشت‌زبانه؛ نه تعریف تحلیلی متفاوت برای هر زبان.

این فهرست تقسیم مسئولیت است؛ فایل خالی صرفاً برای تکمیل فهرست ایجاد نشود. استفادهٔ مشترک باید از قراردادهای تایپ‌شده باشد، نه importهای چرخه‌ای میان admin_ui، reader و worker.

## ۳. مدل دادهٔ پیشنهادی

تمام داده‌ها در schema فعلی Researcher؛ بدون دیتابیس مشترک با Contenter یا Consultant.

| موجودیت پیشنهادی | فیلدهای اصلی / قیود |
| --- | --- |
| `analysis_lenses` | UUID، key یکتا، وضعیت active/archived، اشاره‌گر نسخهٔ منتشرشده، version تراکنشی، زمان‌ها، creator |
| `analysis_lens_revisions` | lens_id، شمارهٔ revision یکتا، تعریف JSON معتبر، SHA-256، وضعیت draft/published/revoked، والد، نویسنده و زمان‌ها |
| `analysis_lens_policy` | singleton: flag، default_lens_id، limits، version؛ default فقط به لنز فعالِ نسخه‌دار اشاره کند |
| `analysis_lens_preview_runs` | Owner، lens_revision/hash، مدل snapshot، مجموعهٔ منبع/hash، generation، نتیجهٔ rubric، زمان انقضا و تأیید |
| `analysis_discovery_snapshots` | مالک کاربر، پروژه، مرکز، as_of، بازه، coverage، candidate IDs و دلایل نسخه‌دار، انقضا |
| context گفتگو | metadata خصوصی `_analysis` شامل snapshot لنز، hash، دامنه، source IDs، resolver version و analysis_version |
| generation فعلی | فیلد nullable `analysis_result` و `audience` با default `reader` و enum `reader/owner_preview`؛ متن answer و citations برای سازگاری حفظ شوند |

جدول preview متن خبر یا پاسخ خصوصی را دوباره کپی نمی‌کند؛ به generation موقت دارای مالکیت و retention وصل است. snapshot discovery هم فقط دادهٔ حداقلی و دلایل لازم نگه می‌دارد؛ با پاک‌شدن کاربر/پروژه حذف می‌شود و روی هر خواندن مجوز مجدد دارد.

قید مرکب FK باید مانع اتصال `active_revision_id` به revision لنز دیگر شود. uniqueness `(lens_id, revision)` و version تراکنشی لازم است. هیچ ویرایش in-place روی revision منتشرشده مجاز نیست. در metadata گفتگو hash تعریف نگهداری شود؛ تعریف لازم برای بازتولید فقط در فضای خصوصی گفتگو، تحت retention آن است.

شناسهٔ migration در زمان توسعه از آخرین main انتخاب می‌شود؛ در این بسته شمارهٔ جدید رزرو نشده است. runtime فقط schema را بررسی می‌کند؛ migration در startup یا deploy عمومی اجرا نشود. RBAC دیتابیس، snapshot preview و policy خارج از schema Researcher ساخته نشوند.

## ۴. چرخهٔ لنز و تراکنش‌ها

۱. ایجاد یا کپی: draft با revision ثابت و `expected_version`.

۲. ذخیره: schema + سقف مجموع + وضعیت ابعاد + بخش‌های الزامی؛ updated hash و نسخهٔ optimistic locking. ویرایش draft نتیجهٔ پیش‌نمایش قبلی را نامعتبر می‌کند.

۳. پیش‌نمایش: اطلاعات فقط از IDهای مجاز حل می‌شود. درخواست با model key، زبان، منابع و hash لنز مشخص و از همان بودجه/صف عبور می‌کند. HTML یا متن خبرِ ارسالی مرورگر منبع معتبر نیست.

۴. فعال‌سازی: transaction با lock لنز و policy؛ نسخه، hash، validation، پیش‌نمایش تکمیل‌شده و تأیید rubric توسط Owner تطبیق داده شوند. تأیید checkbox، اثبات صحت AI نیست؛ صرفاً تصمیم ثبت‌شدهٔ مالک است.

۵. rollback: revision تازه از محتوای revision قبلی؛ audit شامل from/to/hash/actor/زمان، بدون متن خصوصی آزمایش.

۶. revoke: عمل مستقل با دلیل؛ قبل از admission و در چرخهٔ stream بررسی شود، درخواست‌های صفی رد و running طبق کنترل لغو موجود متوقف شوند. مصرف انجام‌شده تسویه و «صفر هزینه» فرض نشود.

فعال‌سازی عادی نسخهٔ N+1 نسخهٔ N را revoke نمی‌کند. گفتگوی قدیمی می‌تواند با نسخهٔ N ادامه یابد، تا مجوز خبر، لنز و policy معتبر باشد. بایگانی لنز مشابه توقف درخواست تازه است؛ نتیجهٔ ذخیره‌شده فقط با مجوز فعلی منابع خواندنی می‌ماند.

فهرست حداقل یک لنز فعال و default معتبر لازم دارد. حذف/بایگانی default فقط با انتخاب صریح جایگزین در همان تراکنش ممکن است؛ fallback مخفی به لنز متفاوت وجود ندارد. حالت feature-off از این الزام برای seed/bootstrap مستثناست.

seed اولیه فقط با عملیات راه‌اندازی و پس از گیت‌های کیفیت فعال می‌شود؛ deploy تعریف و ویرایش مالک را reset نمی‌کند. hash قالب‌ها و نسخهٔ seed ثابت و قابل بازتولید باشند.

## ۵. API پیشنهادی: مدیریت

همهٔ mutationها cookie مستقل Admin، CSRF، Owner واقعی، body محدود و idempotency مناسب دارند. PUT/POST/DELETE مجوز را سمت سرور کنترل می‌کنند؛ مخفی‌کردن component کافی نیست.

| روش و مسیر پیشنهادی | وظیفه |
| --- | --- |
| `GET /admin/api/analysis-lenses` | فهرست صفحه‌بندی‌شدهٔ لنزها و وضعیت/نسخه |
| `POST /admin/api/analysis-lenses` | ساخت/کپی draft؛ key تکراری رد شود |
| `GET /admin/api/analysis-lenses/{id}/revisions` | تاریخچه؛ بدون محتوای خصوصی پیش‌نمایش سایر حساب‌ها |
| `PUT /admin/api/analysis-lenses/{id}/draft` | ذخیرهٔ معتبر با expected_version |
| `POST /admin/api/analysis-lenses/{id}/validate` | اعتبارسنجی بدون AI و بدون هزینه |
| `POST /admin/api/analysis-lenses/{id}/preview` | preview هزینه‌دار؛ پاسخ ۲۰۲ + شناسهٔ اجرای موقت |
| `GET /admin/api/analysis-lenses/previews/{id}` | وضعیت و خروجی preview فقط همان Owner |
| `POST /admin/api/analysis-lenses/previews/{id}/cancel` | توقف و تسویهٔ مصرف |
| `POST /admin/api/analysis-lenses/{id}/publish` | فعال‌سازی revision/hash/preview تأییدشده؛ بدون AI تازه |
| `POST /admin/api/analysis-lenses/{id}/restore` | ساخت draft از revision معتبر قبلی؛ نشر جداگانه |
| `POST /admin/api/analysis-lenses/{id}/revoke` | لغو revision با دلیل و کنترل توقف |
| `POST /admin/api/analysis-lenses/{id}/archive` | توقف لنز و انتخاب جایگزین default در صورت نیاز |
| `GET/PUT /admin/api/analysis-lenses/policy` | تنظیم global فقط برای این قابلیت، بدون تغییر سیاست چت/انتشار |

preview از نشست User استفاده نمی‌کند و نشست Admin را به User تبدیل نمی‌کند. adapter اجرای موجود باید به‌صورت صریح audience نوع `owner_preview` را بپذیرد؛ SSE/وضعیت/لغو مستقلِ دارای auth ادمین می‌خواهد. اتصال مستقیم client ادمین به endpoint دارای cookie User ممنوع است. منابع preview با ACL واقعی Owner حل می‌شوند؛ endpoint مالکیت preview ID را هم بررسی می‌کند. فهرست history/memory/voice/share در User فقط audience نوع reader را می‌پذیرد؛ نسل preview با شناسهٔ معلوم نیز از endpointهای User قابل مشاهده نیست. یک Owner ممکن است هر دو نشست را داشته باشد؛ یکسان‌بودن user_id این مرز را حذف نمی‌کند.

مدل و هزینه در preview همان سیاست AI سرویس را دارند؛ بودجهٔ Owner و سقف‌های سرویس حذف نمی‌شوند. preview پس از ۲۴ ساعت منقضی و متن/گفتگوی موقت آن حذف می‌شود. رسید metadata بدون متن برای audit باقی می‌ماند.

## ۶. API پیشنهادی: Reader و سازگاری

| روش و مسیر | وضعیت / کاربرد |
| --- | --- |
| `GET /user/api/analysis-lenses?assistant_id=…` | جدید: فقط نسخه‌های فعال و metadata مجاز؛ بدون draft یا اسرار |
| `POST /user/api/publications/{pid}/analysis-discovery` | جدید: snapshot محدود؛ AI پولی ندارد؛ publication واقعی و ACL |
| `GET /user/api/analysis-discovery/{id}?cursor=…` | جدید: pagination پایدار و اعتبارسنجی مجدد؛ touch=False برای polling |
| `POST /user/api/publications/{pid}/conversations` | موجود: افزودن optional `analysis_profile` به ResearchStart |
| مسیر ارسال سؤال و SSE فعلی | موجود: افزودن intent `lens_analysis` و optional analysis_version؛ generation همان worker |

نمونهٔ **پیشنهادی** برای شروع گفتگو؛ UUIDها صرفاً نمونه‌اند:

```json
{
  "model_key": "<allowed-provider>:<allowed-model>",
  "source_ids": ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"],
  "memory_ids": [],
  "include_business": false,
  "analysis_profile": {
    "scope": "contextual",
    "lens_id": "33333333-3333-4333-8333-333333333333",
    "lens_revision": 2,
    "lens_hash": "<sha256-of-selected-definition>",
    "discovery_snapshot_id": "44444444-4444-4444-8444-444444444444",
    "lookback_days": 30
  }
}
```

scope نقطه‌ای دقیقاً یک source_id مساوی خبر مرکزی می‌پذیرد و discovery ID ندارد. هاله‌ای دو تا پنج source_id با حضور مرکز و snapshot معتبر می‌پذیرد. انتخاب دستی از میز پژوهش می‌تواند snapshot انتخابِ مجاز از سرور بگیرد؛ IDهای تصادفیِ خارج از candidate/selection snapshot رد شوند.

payload بدون `analysis_profile` رفتار قبلی دارد؛ threadهای قدیمی و intentهای compare/verify/timeline/meeting/action_draft/correction_review بدون لنز به کار ادامه دهند. در thread لنز نسخهٔ اول، `lens_analysis/question/opportunities/risks` مجازند؛ ابزارهای دیگر مسیر فعلی مستقل خود را دارند و lens definition ساختار خروجی آن‌ها را در سکوت عوض نمی‌کند. انتخاب ابزار ناسازگار در UI به شروع درخواست مستقل هدایت و سمت API نیز اعتبارسنجی شود.

شروع گفتگوی تازه، revision/hash فعالِ انتخاب‌شده را با catalog جاری تطبیق می‌دهد. اگر مالک بین نمایش انتخاب و شروع، نسخهٔ فعال را عوض کرده باشد، `lens_revision_changed` بدون هزینه برگردد و کاربر نسخهٔ تازه را دوباره تأیید کند. ادامهٔ گفتگوی قبلاً ایجادشده متفاوت است: revision ثابت خودش را نگه می‌دارد، مگر آن revision یا خود لنز لغو/بایگانی شده باشد.

در thread لنز، تغییر مدل داخل همان provider طبق رفتار فعلی ممکن است، ولی تغییر provider الزام فعلی ساخت گفتگو را حفظ می‌کند. تعویض مدل باید همواره catalog، سقف، ظرفیت و کیفیت پشتیبانی از خروجی را بررسی کند؛ هیچ کلید/API تازه از فرم لنز پذیرفته نشود.

## ۷. نسخهٔ زمینه و حفظ backwards compatibility

`context.version` فعلی برای hash متن/منابع حفظ شود؛ hash لنز را در آن جایگزین نکنیم، چون `validate_context` فعلی آن را با منابع بازسازی‌شده مقایسه می‌کند.

ارسال سؤال در thread جدید علاوه بر `context_version` دارای `analysis_version` برگشتی از سرور است. در thread بی‌لنز، فیلد اضافه لازم نیست و رفتار قبلی حفظ می‌شود. در thread لنز، فقدان/تغییر آن خطای contract قبل از رزرو دارد؛ مقدار ارسالی مرورگر هرگز جای metadata واقعی سرور را نمی‌گیرد.

metadata ثابت در `_analysis` به‌صورت server-generated شامل `schema_version`, `scope`, `lens_id`, `revision`, `definition_hash`, `definition_snapshot`, `resolver_version`, `discovery_as_of`, `source_ids` است. `analysis_version` hash canonical این metadata + context.version + نسخهٔ compiler + نسخهٔ قواعد پایه است. lease، timestamps متغیر، زبان رابط و تغییر صرف مدل به hash معنایی لنز وارد نشوند.

در پاسخ عمومی فقط summary امن شامل ID/نام/نسخه/دامنه/منابع/analysis_version برگردد؛ lease، hash نشست و اطلاعات داخلی مدیریت از `public_context` فعلی نشت نکنند. همان context و citation namespace موجود با `report-N` استفاده شود، نه موتور استناد متفاوت.

پیش از رزرو، worker، هر نوبت follow-up و stream: نشست، ACL، وضعیت published، hash منابع/اصلاحات/حافظه/زمینه کسب‌وکار، لغو لنز و policy بررسی شوند. context_changed قبل از call پولی رد شود. نتیجهٔ تولیدشده پس از حذف منبع نباید همچنان قابل خواندن یا دانلود صوت باشد.

در حذف گفتگو، `analysis_result` و snapshot خصوصی هم پاک شوند؛ نگهداری aggregate مصرف بدون متن می‌تواند طبق قرارداد فعلی باقی بماند. هیچ metadata جدیدی نباید موجب ماندن متن بعد از پاک‌شدن conversation با `SET NULL` شود. tombstone فعلیِ close-before-create و lease در تمام branchهای جدید پوشش آزمون دارند.

## ۸. کشف هاله و جست‌وجوی چندزبانه

نسخهٔ اول بدون paid LLM discovery و بدون معرفی سرویس/مدل برداری جدید طراحی می‌شود. اجرای محدود:

۱. ACL پروژه و مرکز ← freeze زمان `as_of` ← دریافت حداکثر ۵۰۰ publication منتشرشدهٔ همان پروژه در بازهٔ مکمل‌ها، با ترتیب `(published_at,id)` پایدار. متن گزارشِ قابل مشاهده منبع اصلی است؛ ورودی پنهان Admin یا اصل خبر به client یا AI افشا نشود.

۲. حذف مرکز، موارد خارج از مجوز و تکرارهای قطعی با hash متن نرمال‌شده/شناسهٔ مقاله در صورت مجازبودن. منابع syndication را مستقل فرض نکنیم؛ رابطهٔ استقلال نامعلوم آشکار شود.

۳. استخراج عبارت‌ها/نام‌های موجود در متن و تطبیق مفهوم‌های curated چندزبانه: Unicode NFC، فارسی ی/ک و نیم‌فاصله، Arabic diacritics، Latin casefold و aliasهای معتبر شرکت/فناوری. نرمال‌سازیِ جست‌وجو متن اصل را تغییر نمی‌دهد؛ تبدیل کشور/شخص متفاوت به یک entity ممنوع است.

۴. امتیاز داخلی توضیح‌پذیرِ ارتباط از اشتراک entity/عبارت اختصاصی/مفهوم معتبر، تازگی و تنوع. موضوع generic مثل «AI» به‌تنهایی کافی نیست. title/text snippets مربوط به مرکز و مکمل به‌عنوان شاهد دلیل ذخیره شوند.

۵. دسته‌بندی محتاطانهٔ رابطه: همان entity/محصول، پیشینه، همان فناوری/مفهوم یا موضوع وابستهٔ curated. رقابت، علت، وابستگی یا شاهد مخالف فقط اگر در متن/ontology تأییدشده شاهد داشته باشند؛ صرف similarity اجازهٔ چنین برچسبی نمی‌دهد.

۶. انتخاب حداکثر ۵۰ candidate، ده مورد در صفحه؛ دلیل با template محلی و شاهدِ کوتاه، بدون درصد احتمالی یا توضیح آزادِ حدسی مدل. candidate snapshot ده دقیقه معتبر است و به user/project/center/query/corpus version متصل است.

۷. در انتخاب نهایی، وجود ID در snapshot، hash و مجوز همهٔ منابع دوباره بررسی شود. cursor امضاشده یا server-state باشد؛ تغییر cursor دسترسی/محدودیت را دور نزند.

این روش برای متن چندزبانه طراحی می‌شود ولی تضمین بازیابی معنایی همهٔ روابط میان همهٔ زبان‌ها ندارد. alias و ontology ناکافی می‌توانند باعث عدم یافتن شوند؛ پاسخ خالی باید صادقانه باشد. آزمون precision و نمونه‌های cross-language لازم است. اگر کیفیت پذیرش حاصل نشود، توسعه متوقف و طراحی retrieval اصلاح می‌شود؛ یک فهرست صرفاً کلمه‌ای به‌عنوان کشف «هوشمند کامل» منتشر نشود.

بازیابی semantic چندزبانه/embedding یک گزینهٔ مرحلهٔ بعد است: نیازمند انتخاب و ارزیابی مدل، license، نسخه، کارایی، ایندکس خصوصی، ابطال ACL و قرارداد هزینه است. در این بسته هیچ provider جدید یا انتقال پنهانی تمام corpus برای embedding مجاز نشده است. discovery مستقل از لنز است؛ لنز تفسیر را تغییر می‌دهد نه پنهانی مجموعهٔ منابع را.

## ۹. prompt و خروجی ساختاریافته

ترتیب و مرزها: قواعد ثابت سرور ← دامنهٔ مجاز و توضیح نوع منبع ← تعریف معتبر و محدود لنز ← schema نتیجه ← قطعات منتخب/زمینه/سؤال به‌عنوان دادهٔ غیرقابل اعتماد.

تعریف مالک با field-bound serializer ساخته شود؛ هیچ eval، HTML executable، tool definition یا عبارت قابل اجرا پذیرفته نشود. متن لنز باید کلی و بدون secret باشد؛ validation patternهای credential/URL مشکوک را رد یا هشدار دهد ولی ادعای تشخیص همهٔ اطلاعات حساس نکند. اصل مجوز و دسترسی جدا از متن prompt در سرور enforce شود.

خروجی اولیه `lens_analysis` با schema یکنواخت و enumهای محدود دریافت شود. تمام مدل‌های فعال باید adapter سازگار و آزمون معتبر داشته باشند؛ چون برندها متفاوت‌اند، سازگاری API یا Structured Outputs بومی همهٔ آن‌ها فرض نمی‌شود. JSON parse/validation سمت سرور حتی با schema بومی لازم است.

فیلدهای خروجی پیشنهادی:

- `schema_version/summary/reported_claims`: جمع‌بندی و ادعاها با citation IDs.
- `dimensions[]`: شناسهٔ بُعد فعال، applicability، finding، evidence IDs، assumptions و gaps.
- `opportunities/risks[]`: نکته، بُعد، سازوکار، شروط، اتکای adequate/limited/insufficient و شواهد.
- `connections[]`: فقط IDهای منبع منتخب، نوع رابطه، شاهد و فرضیه بودن.
- `counterpoints/next_questions/suggested_checks`: دیدگاه مخالف، سؤال و بررسی پیشنهادی با تمایز منبع/فرضیه.
- `limitations`: منبع AI، پوشش ناقص، دادهٔ ناکافی و محدودیت دامنه.

بُعد غیرفعال/ناشناخته، citation ناموجود، source غیرمنتخب، ادعای منبع ساختگی، مقدار enum نامعتبر و body بیش‌ازحد رد شوند. اعتبار citation ID صحت معنایی استناد را ثابت نمی‌کند؛ سنجش پشتیبانی ادعا در eval و نمونه‌های بازبینی انجام می‌شود. متن استخراج‌شده از output یک summary امن برای history فعلی می‌سازد؛ نتیجهٔ ساختاریافته به engine تازه تبدیل نمی‌شود.

برای درخواست اولیه، تا پایان و validation کامل خروجی، status stream نمایش داده می‌شود؛ raw JSON/تحلیل نامعتبر به‌عنوان پاسخ معتبر نمایش داده نمی‌شود. جواب‌های متنی follow-up از stream فعلی استفاده می‌کنند و تمایز واقعیت/فرضیه و citation validation را حفظ می‌کنند. محدودیت پاسخ و بودجه قبل از اجرا بررسی شود؛ retry/repair پولی پنهانی وجود ندارد. خروجی ناقص failed است، هزینهٔ واقعاً مصرف‌شده ثبت و تلاش جدید به انتخاب کاربر وابسته است.

## ۱۰. هزینه، retry و ظرفیت

یک تحلیل = یک generation در worker فعلی؛ بدون اجرای خودکار چهار لنز. پیش‌نمایش و مقایسهٔ پاسخ دو نسخه هم generation هزینه‌دارند و قبل از اجرا روشن می‌شوند. discovery، validate، draft-save و publish فراخوانی AI ندارند.

رزرو atomic هزینه/توکن، سقف هم‌زمانی فعلی، نرخ، deadline نشست و ledger reuse شوند. idempotency به کاربر و payload ثابت شامل نسخهٔ لنز/منابع/مدل متصل است؛ double-click به دو charge تبدیل نشود. قطع ارتباط بعد از ارسال به provider، مصرف را خودکار صفر/آزاد نمی‌کند؛ حالت unknown و reconciliation فعلی حفظ شود.

prompt کامل، history، sourceها، lens و خروجی باید داخل ظرفیت واقعی مدل جا شوند. بودجهٔ نویسه جای اندازه‌گیری/رزرو محافظه‌کارانهٔ توکن را نمی‌گیرد. زمینهٔ بیش‌ازحد قبل از call رد شود؛ پیشنهاد کاهش منابع/طول خروجی نمایش داده شود. JSON schema حداقل فضای خروجی می‌خواهد؛ مدل/تنظیم کوتاهی که آن را نمی‌پذیرد برای تحلیل اولیه غیرفعال یا با توضیح قبل از هزینه رد شود.

cache نتیجهٔ خصوصی مشترک میان کاربران ساخته نشود. catalog غیرحساس قابل cache نسخه‌دار است؛ active pointer قبل از admission دوباره اعتبارسنجی شود. cache discovery به user/ACL/corpus/as_of متصل و کوتاه‌عمر است.

## ۱۱. خطاهای ماشینی و مشاهده‌پذیری

کدهای جدید پیشنهادی: `lens_unavailable`, `lens_revision_changed`, `lens_revoked`, `lens_definition_invalid`, `lens_definition_too_large`, `draft_conflict`, `preview_required`, `preview_mismatch`, `discovery_expired`, `discovery_coverage_limited`, `no_related_reports`, `analysis_selection_invalid`, `analysis_output_invalid`.

کدهای موجود برای `context_changed`, `news_unavailable`, `quota_exceeded`, `chat_access_denied`, `model_unavailable` و پایان نشست reuse شوند. محدودیت پوشش و no_related_reports وضعیت کاربردی‌اند، نه ۵۰۰ سرور. منابع غیرمجاز ۴۰۴ عمومی می‌دهند؛ وجود منبع خصوصی افشا نشود.

لاگ و metric فقط correlation ID، نوع عملیات، شناسه/نسخهٔ لنز، دامنه، count منابع، مدت، outcome، کد خطا و مقادیر مصرفِ مجاز دارند. سؤال، متن خبر/تعریف/کسب‌وکار، پاسخ، URL کامل، cookie، key یا شناسهٔ شخصی خام وارد telemetry نشوند. IDها طبق الگوی pseudonymization فعلی و cardinality کنترل‌شده ثبت شوند.

audit مالک actor/time/lens/from-to hash/action دارد؛ متن خصوصی preview در آن نیست. هشدارهای کیفیت بر نرخ خروجی نامعتبر، خطای context، timeout، کیفیت retrieval و مصرف غیرعادی متکی‌اند؛ خود لاگ نمونهٔ خبر خصوصی را جمع نمی‌کند.

## ۱۲. امنیت، retention و استقرار

CSRF همهٔ mutationها، CSP سخت‌گیرانه، assets whitelist، renderer امن، محدودیت اندازهٔ body و rate limit discovery لازم‌اند. health-check endpoint management عمومی و نمونهٔ خبر/تعریف حساس در `/health` قرار نگیرد. منع indexing پرتال‌های خصوصی حفظ شود.

TTL پیشنهادی: snapshot discovery ده دقیقه، draft بدون متن خصوصی طبق تاریخچهٔ مالک، preview متن‌دار ۲۴ ساعت، analysis طبق retention/lease گفتگو. پاک‌سازی expiration idempotent و crash-safe باشد. لغو عضویت، حذف پروژه/حساب/خبر و از انتشار خارج‌شدن خبر در export و voice playback هم اثر کنند.

feature flag پیش‌فرض خاموش؛ نبود جداول/seed/مدل سازگار یا ناکافی‌بودن کیفیت، برنامهٔ فعلی را خراب نکند. مراحل انتشار: migration افزایشی با backup محدود Researcher ← seed کنترل‌شده بدون reset ویرایش مالک ← گیت‌های SQL/browser/security/AI ← image امضاشده با commit binding ← استقرار فقط Researcher ← smoke و canary ← فعال‌سازی.

flag این قابلیت اجرای Reader را کنترل می‌کند، نه اجازهٔ آماده‌سازی draft و آزمون مالک در staging. preview فقط با مجوز Owner، policy AI فعال و مدل/سهمیهٔ معتبر قابل اجراست؛ خاموش‌بودن AI سراسری یا آماده‌نبودن schema را دور نمی‌زند. rollout تعریف و شواهد آزمون پیش از نمایش عمومی کنترل‌های جدید ممکن است.

rollback ابتدا flag را خاموش می‌کند، کارهای تازه را متوقف و jobs فعال را drain می‌کند، سپس تصویر قبلی را برمی‌گرداند. schema افزایشی یا نتایج ذخیره‌شده خودکار حذف نمی‌شوند. سازگاری نسخهٔ قبلی با فیلد nullable و metadata context باید در SQL/browser آزموده شود؛ بدون این شواهد، rollback «بی‌ریسک» نامیده نشود. credential، نشست، تنظیمات واقعی پروژه‌ها و سرویس‌های دیگر تغییر نکنند.
