# Bee Researcher v2.90.0

## Roadmap delivery

- MI-167: News List now keeps the six approved columns in order: News, Publication Status, Relevancy Score, Source, News Date, Telegram Publication Date.
- MI-168: Removed saved-view controls from News List.
- MI-169: Unified page and header gutters, including resilient compact-sidebar assistant cards.
- MI-170: Replaced the Appearance theme dropdown with benchmarked selectable theme cards while retaining saved preferences.
- MI-171: Added guided support categories, ticket identifiers/timestamps, user-owned history, owner replies/statuses, and notifications.
- MI-172: Moved Support into the profile menu and removed the primary-sidebar entry.
- MI-173: Fixed assistant-card overflow when the sidebar is minimized.
- MI-174: Added stable minimal default avatars for users without an uploaded avatar; custom uploads still take precedence.

## Verification

- Python syntax and `git diff --check` pass.
- Database migration `0024_support_ticket_categories` is included and runs before service start.
- Existing API contracts remain backward-compatible for old support tickets.
