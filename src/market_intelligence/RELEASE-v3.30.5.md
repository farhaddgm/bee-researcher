# Bee Researcher v3.30.5

## Reliable Media and Topic creation

- Add Media and Add Topic use a single document-level capture handler instead
  of listeners attached to elements that legacy renderers can replace.
- Catalog actions remain available after locale repaints, direct navigation,
  workspace recovery, and page-head redraws.
- Obsolete `onclick` handlers, busy flags, and disabled states are cleared
  during action reconciliation.
- The selected authorized assistant is resolved synchronously before the form
  opens; scoped API authorization remains authoritative when data is saved.
- A failed form open now produces a visible localized error and bounded coarse
  client telemetry instead of silently doing nothing.

## Regression coverage

- Static UI contracts cover delegated source/topic actions and unique controls.
- Browser checks cover clean login, direct Media/Topic routes, reloads, locale
  changes, collapsed navigation, and stale persisted workspace state.
