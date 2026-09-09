# Bee Researcher Back Office v3.20.12

## Browser bootstrap stability

- Fixed a self-sustaining DOM mutation loop in the locale reconciliation layer.
- The enhancement pass now runs after render/language events and no longer observes the entire content tree.
- Support enhancement uses a scoped, idempotent observer; locale reconciliation is event-driven and no longer installs a whole-content observer.
- This prevents the browser from hanging before the login form becomes usable and keeps the authenticated dashboard responsive after refresh.
