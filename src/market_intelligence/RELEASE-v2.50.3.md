# Bee Researcher v2.50.3

## Authentication race hardening

- Responses started under a previous login are discarded after the account changes.
- This prevents a prior account's security rows or workspace data from repainting the current account's screen.
