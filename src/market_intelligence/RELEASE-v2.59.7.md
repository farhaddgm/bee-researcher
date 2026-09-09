# Release v2.59.7

## Theme defaults and legacy theme

- Honey Amber is the default theme for accounts without an explicit theme.
- The previous Default theme remains available in Account settings and can be
  selected again; saved `default` preferences are preserved by the API.
- The login page now starts with the Honey Amber palette, including its
  background, card border and shadow, before any account data is loaded.
- A synchronous theme bootstrap applies an already saved preference before the
  first body paint, avoiding a theme flash on the login page.
