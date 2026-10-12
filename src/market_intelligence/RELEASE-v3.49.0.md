# Bee Researcher 3.49.0

User backoffice AI replies now support Short, Medium, Long and Automatic. Each account can save its default choice and minimum/maximum character targets in Settings; each news discussion has a four-button temporary override beside Response mode. Defaults are Automatic, with 200–600 / 600–1600 / 1600–4000 character ranges. Targets include spaces and citations, are approximate, and do not override evidence requirements or model/token ceilings.

The server applies saved preferences to every User chat flow, including selected research, comparisons, critiques and meeting briefs. Requests capture a validated length snapshot before reserving tokens; retries keep that snapshot, and changed explicit parameters cannot reuse the same idempotency key. Settings require increasing, integer ranges within 1–20,000 characters.

This production cutover also includes the merged 3.48 token-quota releases: owner defaults and project/account overrides for rolling six-hour, daily, monthly and lifetime input+output token ceilings, private per-account usage reports, conservative reservations and native provider usage settlement. Existing accounts start with unlimited ceilings until the owner configures them. Six-hour limits roll continuously; calendar boundaries use Asia/Tehran.

Schema 0051 adds only quota settings and token usage accounting. The scoped release path backs up the Researcher schema before migration, checks the restricted runtime role, verifies the signed main image and replaces only the Researcher application.

Validation covers preference persistence/isolation, invalid range prevention, eight locales at desktop/mobile widths, keyboard and accessibility behavior, frozen generation prompts and idempotent retries, all four quota windows and private consumption reports using synthetic providers and real isolated PostgreSQL.
