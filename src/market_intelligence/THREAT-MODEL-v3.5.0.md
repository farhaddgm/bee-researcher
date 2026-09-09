# Bee CFO v3.5.0 — Phase-Two Data Boundary Threat Model

## Scope

Phase one processes public market data, public source metadata, report
snapshots, and operational audit records. It does **not** collect or process
holdings, transactions, goals, risk tolerance, identity documents, contact
details, or personalised recommendations.

## Assets and boundaries

- Bee CFO runs in the `market_intelligence` schema, Redis database `2`, and
  `market-intelligence:*` namespace.
- Bee Researcher and Consultant retain separate tables, queues, configs,
  delivery records, and release lifecycles.
- Telegram tokens remain deployment secrets. Google Sheets and Bee CFO APIs
  carry no credentials.
- The v3.5.0 governance ledger stores only non-personal verification and
  configuration evidence.

## Threats and controls

| Threat | Control | Evidence |
| --- | --- | --- |
| Cross-project data access | Assistant-scoped queries and foreign keys | API access check; `test_isolation` |
| Source manipulation or format drift | Owner decision, UAT state, unit/timezone/fallback contract | source-decision ledger |
| Alert spam or replay | Severity threshold, quiet hours, cap, dedup and append-only decision | attention-policy evaluator |
| Prompt injection through a request | Typed `/why <UUID>` only; stored evidence only; no model call | `why_changed` audit |
| Unauthorised bot use | Private-chat-only command and configured username allow-list | runtime gate |
| Premature personal-data use | Phase-one validator rejects it and phase-two processing flag | privacy-boundary API and unit tests |
| Loss of deletion/export rights in phase two | Consent, minimisation, retention/deletion and export/delete are mandatory future controls | boundary contract |

## Phase-two entry gate

No personal-data connector, portfolio analysis, or recommendation engine may
be enabled until a separate design has explicit consent language, retention
periods, delete/export workflows, tenant-isolation tests, a reviewed threat
model, and an owner-approved release gate. Those controls are represented here
as a design contract; they are not activated by v3.5.0.
