# Bee Researcher Admin — UX benchmark and improvement catalog

This is the implementation checklist for the admin back office. The list is
deliberately short per item so it can be reviewed by product and engineering
without turning the Support screen into a second specification.

## Benchmark principles

- Use an 8px spacing rhythm and shared design tokens.
- Keep page containers aligned and prevent horizontal overflow.
- Treat Support as a queue: search, status, priority, ownership and a clear
  empty/error state are first-class controls.
- Use one button hierarchy: primary for the page goal, neutral for secondary
  actions, danger only for destructive actions, and one consistent control
  height.

## Support — 50 practical improvements

1. Equal-width compose and ticket panels — implemented in `admin-support-final`.
2. One clear page title and short description — implemented.
3. Summary counters for total/open/in-progress/waiting/resolved — existing v2.
4. Search by ticket number, subject, user and body — existing v2.
5. Priority filter — existing v2.
6. Status tabs — existing v2.
7. Debounced search (260ms) — existing v2.
8. One-click clear search — existing v2.
9. “Other” topic with a required subject — existing v2.
10. Body length validation and counter — existing v2.
11. Four visual priority buttons with a native form value — existing v2.
12. Disable submit while sending — existing v2.
13. Human-readable success/error messages — existing v2.
14. Retry action when loading fails — existing v2.
15. Skeleton-friendly loading region — supported by shared loading styles.
16. Owner-only all-ticket queue — existing v2.
17. Owner reply editor inline in each ticket — existing v2.
18. Status transition in the same ticket card — existing v2.
19. Ticket number as a scannable eyebrow — implemented.
20. Status and priority badges — existing v2.
21. Created-by and workspace metadata — existing v2.
22. Preserved line breaks in issue details — implemented.
23. Empty state that explains the next action — implemented.
24. No-match state that reflects active filters — existing v2.
25. Responsive one-column layout below 900px — implemented.
26. Mobile priority buttons collapse to two columns — implemented.
27. Mobile toolbar collapses to one column — implemented.
28. Keyboard-focus ring on every actionable control — shared button layer.
29. Minimum 40px primary button target — shared button layer.
30. Consistent card radius, border and shadow — implemented.
31. No native controls leaking into the layout — final CSS fallback.
32. Ticket list has a bounded scroll region — existing v2.
33. Owner queue is visually separated from personal tickets — implemented.
34. Form labels remain visible above controls — implemented.
35. Long subjects wrap instead of overflowing — implemented.
36. Long bodies wrap and preserve formatting — implemented.
37. Loading state cannot submit twice — existing v2.
38. Refresh keeps the current filter model — existing v2.
39. Language changes re-render the whole Support surface — existing v2.
40. RTL/LTR direction is set at the Support root — existing v2.
41. Reduced-motion support for loading — existing v2.
42. Screen-reader labels on search and tabs — existing v2.
43. Active tabs expose `aria-selected` — existing v2.
44. Owner-only controls are hidden for non-owners — existing v2.
45. Ticket reply status is announced through toast/status — existing v2.
46. All Support controls use the global button hierarchy — shared layer.
47. No duplicate page-head actions — final cleanup pass.
48. Obsolete evidence/content-edit actions are removed — final cleanup pass.
49. Support CSS is isolated under `#view-support` — implemented.
50. A single final hardening pass repairs late-rendered DOM — implemented.

## Admin-wide UI/UX and feature improvements — 50 ideas

1. Tokenize spacing, color, radius and control height — implemented.
2. Use the 8px grid for action groups — implemented.
3. Align page-head actions to one side — implemented.
4. Keep primary action first in visual hierarchy — implemented.
5. Reserve red/pink for destructive actions — implemented.
6. Add consistent hover/focus/disabled states — implemented.
7. Make controls full-width on narrow screens — implemented.
8. Remove the obsolete page-context pill — implemented.
9. Remove duplicate page-head buttons — implemented.
10. Remove obsolete “View evidence” actions — implemented.
11. Remove obsolete “Edit content” action — implemented.
12. Keep table headers sticky within their scroll container — existing UI.
13. Prevent table columns from shifting after rendering — existing publication schema.
14. Use server-generated media/topic IDs — existing API.
15. Provide a direct media creation path — implemented.
16. Keep AI source suggestions optional — implemented.
17. Validate media URLs before submit — implemented in the direct form/browser.
18. Probe a newly-created media source without publishing — existing source probe.
19. Show source health and last error — existing observability UI.
20. Show received/analyzed source counts — existing observability UI.
21. Support a business-free assistant — implemented in API and pipeline fallback.
22. Use a neutral general-market analysis context — implemented.
23. Make Business name optional in the assistant form — implemented.
24. Keep assistant readiness truthful for general-market mode — implemented.
25. Avoid cross-workspace business/source/topic leakage — existing scoped loaders.
26. Keep user/project lists loading-gated — existing project-list gate.
27. Show loading instead of stale cards during access checks — existing UI.
28. Add one responsive content max-width — implemented in Support and shared pages.
29. Preserve RTL/LTR at the view boundary — existing locale layer.
30. Avoid un-nonced dynamic styles under CSP — existing nonce reuse plus final CSS.
31. Make loading bars non-blocking — existing UX layer.
32. Add reduced-motion behavior — existing UX layer.
33. Use accessible names for icon-only buttons — existing shell.
34. Keep destructive confirmation copy explicit — existing handlers.
35. Keep all API writes idempotent where possible — existing server contracts.
36. Surface server validation messages in friendly language — existing `friendlyError`.
37. Add empty states that explain how to recover — existing views.
38. Keep filter controls adjacent to the table they control — existing views.
39. Use concise labels that fit buttons — existing locale catalogs.
40. Keep Latin IDs in an isolated LTR style — existing `data-latin` rules.
41. Keep numbers locale-aware without mutation loops — existing locale functions.
42. Never render raw HTML from article titles — existing escaping/sanitizing.
43. Keep source credentials out of the browser — existing server-env policy.
44. Use bounded source probe requests — existing backend probe contract.
45. Keep owner-only template editing visibly labeled — existing Owner-only badge.
46. Keep channel readiness separate from collection settings — existing view split.
47. Keep feedback review separate from automatic model updates — existing workflow.
48. Keep account access controls project-scoped — existing access service.
49. Expose the release version in the sidebar for support diagnostics — existing shell.
50. Add a final DOM hardening pass after late compatibility scripts — implemented.

The two lists are intentionally conservative: they improve hierarchy, clarity,
accessibility and reliability without replacing the product’s existing visual
language with a new theme.
