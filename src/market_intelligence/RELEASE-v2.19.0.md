# Bee Researcher v2.19.0

## Backoffice configuration and lifecycle controls

- Add, edit, enable/disable, and delete workspace-scoped media and topics.
- Configure numeric Telegram feedback and observer channel IDs per assistant without exposing the bot token.
- Rename the legacy default workspace to `داتین`; keep `دستیار تحقیقات داتین` as its separate existing assistant.
- Delete assistants safely as an admin; the default Dotin assistant is protected.
- Add the missing backoffice controls and hide the non-actionable “all assistants” selector option.

## Verification

- Migration `0008_default_workspace_name` is idempotent.
- The full regression suite passes before deployment.
