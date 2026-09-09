# Bee Researcher / Market Intelligence v3.10.2

## Bee CFO pilot-integrity guard

- A report can contribute to the Bee CFO pilot ledger only once, unless its
  prior failed operator entry was explicitly suppressed with its audit trail
  retained.
- Verified no-send pilot observations for the same watch require a minimum
  four-hour interval. The guard reads legacy report relations too, so it is
  effective for observations recorded before this release.
- The cooldown neither calls Telegram nor changes scheduler state. The existing
  profile gate remains the only path to automatic publication.
