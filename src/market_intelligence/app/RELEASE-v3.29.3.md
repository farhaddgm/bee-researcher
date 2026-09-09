# Bee Researcher v3.29.3 — Telegram source probe and extraction health

- Added a dedicated parser for public Telegram `t.me/s` pages. It extracts
  message text, caption, permalink, publication time and media metadata while
  skipping media-only posts that cannot be analyzed.
- A successful HTTP response with no extractable items now marks the source as
  `degraded` and records an actionable extraction error instead of reporting a
  false healthy state.
- Added source observability metrics (received/analyzed counts, last/next
  crawl and last error) to the admin Media page.
- Added an owner/editor-safe, bounded “Check source now” action. It fetches at
  most 20 recent items, shows staged progress, scores relevance, surfaces the
  top five and borderline (within 0.10) results, and never publishes.
- Newly saved and approved sources automatically start this limited check.
