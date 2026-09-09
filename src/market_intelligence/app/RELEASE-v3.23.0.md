# Bee Researcher v3.23.0 — User reading experience

## Benchmark and decision

Google News establishes the save-for-later pattern, while Intercom documents
scoped search, combined filters, explicit sort choices, custom views and
keyboard shortcuts. These patterns are adapted to a read-only, project-scoped
news reader. The direction change follows the HTML bidirectional-text model:
the document chrome stays in its normal direction and only the selected news
content receives the reader direction.

- [Google News — Save stories](https://support.google.com/googlenews/answer/7690211)
- [Intercom — Inbox search and filter](https://www.intercom.com/help/en/articles/6516006-inbox-search-and-filter)
- [Intercom — Custom views and folders](https://www.intercom.com/help/en/articles/6588834-organize-your-inbox-with-custom-views-and-folders)
- [MDN — HTML global `dir` attribute](https://developer.mozilla.org/en-US/docs/Web/HTML/Global_attributes/dir)

## Twenty new ideas implemented in this iteration

1. Scope RTL/LTR to news title and body only; keep all chrome unchanged.
2. Automatic direction mode for mixed-script news.
3. Apply the same content direction to the full-news dialog.
4. Deep-link assistant, search, view, sort and date filter in the URL.
5. Restore the selected assistant and filters after sharing/reopening a link.
6. One-click clear-search control.
7. One-click clear-all-filters control.
8. News font-size preference (small/medium/large).
9. News line-spacing preference (tight/normal/loose).
10. Copy full news text from the details view.
11. Native Web Share support with clipboard fallback.
12. Print-focused full-news view.
13. Skip-to-news accessibility link.
14. Reduced-motion support for sensitive users.
15. Focus returns to the originating card after closing details.
16. `j`/`k` keyboard card navigation.
17. `s` keyboard save/unsave action.
18. Skeleton loading state with `aria-busy`.
19. Abort stale refreshes and retain the last usable snapshot on failure.
20. Server-side search now matches message text, source name and source key.

## Verification and boundary

- Existing suite: ۳۰۰ tests pass.
- User portal contract: ۴ tests pass.
- `/health`: healthy, PostgreSQL and Redis healthy.
- `/user`: HTTP 200 with noindex/nofollow and nonce-based CSP.
- Unauthenticated `/user/api/me`: HTTP 401.
- No database migration or publishing capability was added; saved/read states
  remain local to the reader's browser.
