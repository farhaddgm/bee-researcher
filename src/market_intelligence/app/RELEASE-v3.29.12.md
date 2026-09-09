# Bee Researcher Admin — v3.29.12

## Support visibility fix

- The support root now always uses the shared `view` class when created.
- Legacy support roots are normalized to that visibility contract as well.
- Support content is hidden with every other inactive view and appears only when the dedicated Support route is active.

## Verification

- Python syntax and `git diff --check` pass.
- Full service tests pass before deployment.
- Deployed health and public health checks pass.
