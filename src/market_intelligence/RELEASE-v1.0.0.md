# Market Intelligence v1.0.0 release record

Release date: 2026-08-10

## Deployed scope

- MI-004 full article extraction and provenance
- MI-005 relevance scoring and event clustering
- MI-006 structured business analysis with deterministic fallback and cost caps
- MI-007 Telegram preview, permission, idempotency, audit and feedback workflow
- MI-008 Tehran scheduler, locking and missed-slot recovery
- MI-009 pilot controls, metrics, rescore and UAT support
- MI-010 weekly reports, retention policy, operational docs and rollback support

## Evidence

- 25/25 Market Intelligence unit and contract tests passed.
- Online Alembic upgrade to `0003_full_pipeline` and downgrade to
  `0002_source_registry` passed in an isolated PostgreSQL instance.
- Production schema reports `1.0.0 / mi-010`.
- Safe live pilot: four healthy media sources, 20/20 complete extractions, five
  relevant analyses and five Telegram previews; no Telegram publication.
- After explicit owner approval, exactly five selected public articles and the
  approved Dotin profile were analyzed through OpenAI Structured Outputs with
  `gpt-5.6-luna`: 5/5 succeeded, confidence was 0.72--0.84, and estimated total
  cost was $0.0118486. The verified results are in `لاگ اخبار!A2:N6`.
- Post-deployment custom dump:
  `backups/postgres/post-mi-v1-20260810-065937.dump`.
- The dump restored successfully in an isolated PostgreSQL 17.10 instance with
  40 normalized articles, seven analyses, seven publications and one weekly
  report.

## Operational gates still closed

- Recurring OpenAI analysis/embeddings: the one-time five-item approval has been
  consumed. The application egress gate is closed again pending explicit
  approval for recurring scheduled analysis.
- Telegram delivery is fully configured for the private channel. The bot is an
  administrator and the live readiness check confirms post/edit/delete
  permissions. After explicit UAT approval, exactly one selected OpenAI preview
  was published successfully as Telegram message `4`. Pilot mode remains
  enabled, auto-publish remains disabled, and the remaining previews were not
  published.
- Stable release acceptance: requires owner UAT/feedback and the seven-day soak.

Do not label MI-006, MI-007, MI-009 or MI-010 operationally complete until their
corresponding gates are satisfied. Code deployment and operational acceptance are
tracked separately.
