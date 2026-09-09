# Bee Researcher — v3.15.2

## CSP migration — first class extraction

- Eleven static inline style attributes in the legacy back-office shell were
  replaced with named CSS classes; visual behavior remains unchanged.
- The staged inline-style budget is now **51** (previously 62), so new inline
  presentation cannot be added silently.
- The strict `Content-Security-Policy-Report-Only` header and bounded report
  endpoint from v3.15.1 remain enabled. The enforcing compatibility policy is
  unchanged until browser smoke validates the remaining dynamic templates.

## Verification

- Full test suite: **273 tests passed**.
- Python syntax, CSP budget and production health checks passed.
- Production is running `ai-market-intelligence:3.15.2`.
