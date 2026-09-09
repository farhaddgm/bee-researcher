# CSP migration plan

The back-office currently uses a nonce-based CSP for script and style blocks.
Two narrowly scoped compatibility directives remain because the legacy shell
still contains inline `onclick` and `style` attributes.

Migration sequence:

1. Replace inline event attributes with delegated listeners and stable data
   attributes.
2. Replace inline style attributes with named classes and design tokens.
3. Enable `Content-Security-Policy-Report-Only` in staging and inspect every
   violation during login, project switching, modals and template editing.
4. Enforce the policy without `script-src-attr 'unsafe-inline'` or
   `style-src-attr 'unsafe-inline'`, then keep a regression test on the header.

Current stage (v3.17.0): the strict policy is emitted as
`Content-Security-Policy-Report-Only` with the same-origin report endpoint
`/admin/api/security/csp-report`. Reports are bounded, limited to safe fields,
and redact credentials before logging. The enforcing header deliberately keeps
the two compatibility directives until browser smoke confirms that no control
depends on them. Legacy event/style attributes are now converted at runtime to
ordinary listeners and nonce-authorised stylesheet classes; the CI budget is
fixed at 42 event attributes and 54 style attributes while the remaining shell
is migrated. The next step is to run browser smoke, review CSP reports and
remove each compatibility exception.

The compatibility exception stays until the browser smoke suite is green; a
partial removal would break existing controls and is not a safe production
change.
