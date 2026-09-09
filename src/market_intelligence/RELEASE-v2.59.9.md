# Release v2.59.9

## Private indexing and legacy host behavior

- The previous hostname now returns `404 Not Found` and never redirects to the
  researcher subdomain.
- Added `robots.txt` with `Disallow: /` and `noindex, nofollow, noarchive,
  nosnippet` meta and response headers for the private control plane.
- Added baseline privacy/SEO headers (`X-Content-Type-Options` and
  `Referrer-Policy`) without exposing a public sitemap.
