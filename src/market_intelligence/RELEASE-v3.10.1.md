# Bee Researcher / Market Intelligence v3.10.1

## Bee CFO verified pilot runner

- Added a no-send verified pilot endpoint: `POST /bee-cfo/pilot/verified-runs`.
- The runner captures an approved direct quote, evaluates the persisted
  evidence gate, records a private canary and shadow run, and derives the full
  pilot checklist from those typed receipts.
- The runner never invokes Telegram delivery and never activates a scheduler.
- This removes error-prone manual mapping of wrapper fields during pilot audit
  registration while preserving the existing append-only governance ledger.
