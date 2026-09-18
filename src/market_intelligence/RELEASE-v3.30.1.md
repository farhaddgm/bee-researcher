# Bee Researcher v3.30.1

- Unified the `/user` login surface with the admin login composition: shared
  card dimensions, Bee Researcher logo placement, input treatment, inline
  validation, primary action, and language selector.
- Made Media and Topic action bindings stable across legacy table redraws.
  The action handler now binds once at the target and resolves the authorized
  workspace before opening the dialog.
- Hardened the browser interaction smoke test to assert visible modal content
  rather than the zero-size modal root, and made its output compact for CI.
