# Bee Researcher 3.36.0 — shared backoffice usability contract

- Responsive admin header replaces overflowing absolute coordinates.
- Collapsed sidebar hides only direct footer labels, not nested profile-menu
  labels or avatar initials; navigation stays on a non-default current page.
- Action height/type is consistent; widths follow labels, not the widest sibling.
- Assistant cards contain all translated actions, metadata and long titles.
- Search/filter toolbars wrap independently from table headers.
- Tables scroll within named keyboard-focusable regions; empty cells remain
  table cells and span the actual header count, including optional selection.
- Equal desktop Support columns stack on compact viewports; theme-aware fields
  and conversation surfaces preserve existing threaded ticket permissions.
- Shared modern form primitives cover Reader settings and dark Support fields.
- Viewport-positioned translated information tips support hover, focus and tap.
  Focus-triggered scrolling repositions rather than dismisses the description;
  dismissing a tip restores its trigger's original ARIA description.
- Long translated overview timeline rows reflow within compact cards; health
  and review surfaces follow the selected theme.
- Error toasts persist until dismissal, with a close action and alert semantics;
  successes retain timed status announcements. Message text is never HTML.
- Reader settings use a real 3/2/1-column layout and a larger notification switch.
  Skeletons cover assistant/support cards, clean up hosts, and respect reduced motion.
- Both portals share a separate presentation controller without network requests,
  polling or additional MutationObservers. Login and news-only text direction
  remain unchanged. Added static contract and browser regression tests.
  The UI regression suite is also a required browser workflow step.

No database migration or production account/model/schedule/source/topic change.
Benchmarks, root causes and boundaries: docs/ui-usability-3.36.0-fa.md.
Runtime publication is documented separately after actual release checks.
