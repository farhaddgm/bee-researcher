# Bee Researcher v2.51.0

## MI-068 — Feedback metrics

- Feedback report requests are now scoped to the selected project, so the overview cards and the feedback page use the same real project data.

## MI-069 — Recoverable project deletion

- Project deletion is now a soft delete.
- The owner sees deleted projects in a separate section for 30 days and can restore or permanently delete them.
- Non-owner accounts never receive deleted-project rows or recovery endpoints.

## MI-070 — Freshness limit

- The freshness window is enforced at 1–7 days in config, API, runtime resolution, and UI.

## MI-071 — Close other sessions

- Other sessions are selected and removed explicitly, preserving the current session and returning a reliable count.

## MI-072/073/074 — Back-office polish

- Sidebar version remains the service version, the hamburger control collapses/expands the sidebar, Persian login placeholders are right-aligned while entered credentials remain left-aligned, and the logout label no longer loses its icon/text span during language changes.

## MI-075 — Scoped user creation

- Global administrators can create lower-level users and assign only projects visible to the current account; the server remains the final authorization boundary.

## MI-067 — Telegram notification mode

- Each project can choose normal or silent Telegram notifications. The setting is passed as `disable_notification` for scheduled, manual, and observer delivery and is stored in the runtime audit path.

## Pending external prerequisite

- MI-066 (WhatsApp) remains blocked until the owner supplies Meta Business/WABA, verified number, approved app/token, public HTTPS webhook, and the product choice between WhatsApp Business Cloud API and WhatsApp Channel.
