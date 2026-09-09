# HTTPS عمومی بک‌آفیس

پیکربندی Caddy آماده و validate شده است. برای فعال‌سازی واقعی مسیرهای HTTPS،
دامنه‌ی Researcher و دامنه‌ی Bee Consultant را در DNS به همین IP وصل کنید.
دامنه‌ی Bee Consultant برای بک‌آفیس روی مسیر `/admin` ارائه می‌شود.
دامنه‌ی `hero.beeproject.ir` نیز از همین Caddy به control plane سرویس Hero
روی شبکه‌ی خصوصی Docker متصل است و با Basic Auth محافظت می‌شود.

ورودی‌های لازم:

1. یک دامنه یا زیردامنه، مثلاً `research.example.com`.
2. رکورد DNS نوع `A` برای همان نام به IP `82.115.8.115`.
3. قرار دادن مقدار دامنه در `.env`:

```env
MARKET_INTELLIGENCE_DOMAIN=research.example.com
CONSULTANT_BEE_DOMAIN=consultant.example.com
HERO_DOMAIN=hero.beeproject.ir
HERO_BASIC_AUTH_USER=hero-admin
HERO_BASIC_AUTH_HASH=<bcrypt-hash>
```

Hero باید روی شبکه‌ی Docker خارجی `hero_hero-private` و با نام سرویس
`control-plane` در دسترس باشد. پورت host آن (`127.0.0.1:43100`) فقط برای
دسترسی اضطراری محلی است و نباید در Caddy به‌عنوان upstream استفاده شود.

بعد از انتشار DNS و اطمینان از resolve شدن دامنه:

```bash
docker compose --profile market-intelligence --profile market-intelligence-https up -d market-intelligence market-intelligence-https
```

Caddy گواهی Let's Encrypt را خودکار می‌گیرد. دامنه‌ی Researcher به سرویس
`market-intelligence:8010`، دامنه‌ی Bee Consultant مسیر `/admin` و APIهای لازم
را به `consultant-bee:8020`، و دامنه‌ی Hero را به `control-plane:3100`
reverse-proxy می‌کنند. پورت‌های مستقیم سرویس‌ها فقط روی localhost یا شبکه‌ی
خصوصی bind هستند و از اینترنت قابل دسترسی نیستند. برای دسترسی اضطراری محلی
می‌توان از SSH tunnel استفاده کرد:

```bash
ssh -L 8010:82.115.8.115:8010 user@server
```

سپس آدرس پنل را از طریق tunnel روی دستگاه محلی باز کنید.
