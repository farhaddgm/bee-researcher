# Bee Researcher / Market Intelligence v3.10.0

## Secure source connector foundation

- Added Telegram public/private, Instagram public/private and X public/private
  source adapter contracts.
- Public Telegram sources use the public channel view and robots policy.
- Instagram and X use official JSON/API responses; private adapters require an
  explicit `private_authenticated` policy and a server-side credential
  reference.
- Credential values are environment-only and are never accepted in source URL
  query strings, stored in the sheet, or written to source item metadata.
- Added SSRF/credential-in-URL validation and minimal social payload parsing.
- Added schema migration `0033_social_source_connectors` and connector tests.

Private connectors remain safely gated until the owner configures official
provider credentials. A missing credential is reported as a source health
failure without exposing any secret.
