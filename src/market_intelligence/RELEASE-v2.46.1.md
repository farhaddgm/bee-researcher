# Bee Researcher v2.46.1

## Overview KPI bootstrap hardening

- Added an independent, retrying client bootstrap for the overview KPI cards.
- The bootstrap validates the active assistant and waits for successful metrics, source, and health responses before painting values.
- It no longer depends on the larger dashboard initializer or the global digit formatter, preventing the `—`/«در حال بررسی» placeholders from remaining after a partial client-side failure.
- Kept the existing localized Persian/English KPI output and deployed the patch as version `2.46.1`.
