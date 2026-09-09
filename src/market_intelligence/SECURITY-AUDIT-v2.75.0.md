# Bee Researcher security audit — v2.75.0

## Scope

The FastAPI control plane, cookie session flow, operational endpoints, admin HTML shell and reverse-proxy-facing headers were reviewed.

## Findings and resolutions

| Finding | Resolution |
| --- | --- |
| Deployment metadata was readable without a session | `/meta` now requires an authenticated admin session. |
| Operational mutation routes could be called without a session | Manual ingestion uses workspace write scope; maintenance and publication routes require the owner. |
| Cookie-authenticated mutations had no same-origin guard | State-changing `/admin/api` requests with an Origin header must match the forwarded/request origin. |
| Browser hardening headers were incomplete | CSP, X-Frame-Options, Permissions-Policy, COOP, CORP, no-store and conditional HSTS are now emitted. |
| Security navigation was duplicated after moving controls into Account | The standalone Security button is removed; the account security panel remains available. |
| Dynamic English labels appeared in Persian during refresh | Settings and Account controls are created using the current persisted language before the authenticated shell is revealed. |

## Operational requirements

- Keep the service behind HTTPS in production so HSTS is active.
- Keep secrets in the server environment/secret store; never enter bot or API tokens in the roadmap sheet or UI profile fields.
- Keep database and Redis networks private and expose only the reverse-proxy port.
