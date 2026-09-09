# Release v2.62.0

## MI-066 — WhatsApp readiness gate

- Added a disabled-by-default, secret-free WhatsApp readiness contract for `cloud_api` and `channel` destinations.
- Added `GET /whatsapp/readiness`; it is workspace-scoped and never sends a message or exposes credentials.
- Added a fail-closed client stub so no WhatsApp network call can occur before official Meta validation.
- Added HTTPS webhook and destination validation at configuration boundaries.
- Production delivery remains blocked until the owner supplies the Meta prerequisites recorded in the roadmap.
