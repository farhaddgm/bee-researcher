# Bee Researcher v2.69.0

## Friendly validation and error messages

- Replaced the browser's native English `Please fill out this field` prompt on the login form with inline, Persian-friendly messages such as «نام کاربری را وارد کنین.» and «رمز عبور را وارد کنین.»
- Added visible error styling and accessible `role="alert"` feedback for the two login fields.
- Normalized API, permission, network and form errors through one language-aware formatter.
- Persian errors use a formal-friendly second-person plural tone; English errors remain clear and polite.

## Verification

- Market-intelligence tests: 134 passed.
