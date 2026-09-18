# Bee Researcher v3.30.2

- Stabilized the Media and Topics action path: every click resolves the current authorized assistant, resets its busy state, and now reports a localized error instead of failing silently.
- Added public-domain end-to-end coverage for opening both creation dialogs across every assistant available to the owner.
- Bundled the required Vazirmatn weights locally and serve them through the allow-listed asset endpoint. This removes the blocked third-party stylesheet request while preserving the strict CSP.
- Kept the Admin and User sign-in surfaces visually identical, including the local font preload.
