# Bee Researcher v2.16.0

## Backoffice UX foundation

- Replaced the single-page operational layout with a responsive RTL application shell.
- Added context-aware workspace navigation for overview, assistants, content review, sources, topics, scheduling, operations, quality and team security.
- Replaced prompt/JSON editing for common assistant, source, topic, business profile and user actions with validated forms and modal workflows.
- Added an actionable overview dashboard with pipeline stages, source health, recent publications and next actions.
- Added a content review queue with search, status filters and a detail drawer for publication previews.
- Added operational health, Telegram readiness, feedback quality and team/session views.
- Kept the existing FastAPI endpoints and workspace scoping; no credentials are rendered in the UI.

## Verification

- Python syntax check passed for `app/admin_ui.py`.
- Existing API and database contract remains unchanged; run the full regression suite before deployment.
