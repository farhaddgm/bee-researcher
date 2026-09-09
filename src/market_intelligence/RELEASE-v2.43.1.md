# Bee Researcher v2.43.1

Fixes a front-end bootstrap failure caused by a removed legacy business button.
The failure occurred before later client initialization, leaving the overview,
feedback report, weekly schedule, and Telegram channel management stale or
empty despite healthy API responses. The legacy binding is now optional, so
the current workspace loader and all page renderers always start.
