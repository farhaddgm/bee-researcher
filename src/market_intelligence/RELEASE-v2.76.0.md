# Bee Researcher v2.76.0

## Approved roadmap ideas delivered

- MI-126 / I-045: owner-only quick assistant setup. A short natural-language mission produces a non-persistent editable draft; the existing full setup remains available and nothing is created until confirmation.
- MI-127 / I-052: feedback learning center with period metrics, per-source precision, safe ranking-change snapshots, and owner-only rollback.
- MI-128 / I-055: event-cluster evidence endpoint and insights payload; non-representative articles stay reviewable but are excluded from duplicate publication.
- MI-129 / I-056: project-scoped business knowledge library with revision history and injection into analysis context; access follows workspace RBAC.
- MI-130 / I-058: project privacy controls for retention/data region/export plus a bounded, secret-free JSON export and audit event.

## Safety notes

- Quick drafts are never persisted before owner confirmation.
- Generated settings cannot carry tokens, passwords, channel IDs, or webhooks.
- Feedback learning is read-only until the existing explicit ranking action is used; rollback is available only for a recorded score snapshot.
- Workspace exports omit runtime secrets and destination credentials.

## Verification

- `python3 -m compileall -q app/market_intelligence/app`
- `git diff --check`
- Docker image `ai-market-intelligence:2.76.0` builds successfully. Production restart is intentionally pending explicit deployment approval.
