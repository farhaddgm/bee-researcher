# CSP enforcement and rollback notes

The back-office now serves a nonce-based strict Content Security Policy by
default. It does not allow `unsafe-inline` in `script-src`, nor does it add
`script-src-attr` or `style-src-attr` exceptions. Legacy inline attributes in
the server-rendered shell are transformed before the browser executes them.

`Content-Security-Policy-Report-Only` remains enabled as a parallel signal,
using the same-origin `/admin/api/security/csp-report` endpoint. Reports are
bounded and redacted. The CI attribute count is only a regression guard on the
legacy markup consumed by the transformer; it is not a security allowance.

Browser CI exercises authenticated interactions under the strict enforcing
header. If a real production regression requires emergency rollback,
`MARKET_INTELLIGENCE_CSP_STRICT=false` is an explicit temporary compatibility
switch. It must be removed again after the failure is fixed; it is not the
documented steady state.
