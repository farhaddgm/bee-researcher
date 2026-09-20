# Bee Researcher v3.30.11

## Verified media workflow

- Media management now has three clear actions: health check, media
  suggestions and review-first media add.
- The add flow asks for a name and optional operator guidance, then tests the
  proposed public connector before allowing final registration.
- Empty discovery results report an honest no-result state and similarly
  named alternatives when available.
- Health checks reuse the production connector and parser and never publish.

## Data boundary

- Only the name/keyword and optional guidance entered by the operator reach
  the optional drafting provider. Project, business and source-list data stay
  within Bee Researcher.
