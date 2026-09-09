# Bee Researcher v2.46.2

## Overview KPI overwrite protection

- The overview bootstrap now records the expected KPI values and detects any later DOM overwrite.
- A bounded retry loop and `MutationObserver` repaint the cards when a legacy or partial dashboard render replaces valid values with `0`, `—`, or «در حال بررسی».
- The fix preserves the selected language and workspace and is deployed as `2.46.2`.
