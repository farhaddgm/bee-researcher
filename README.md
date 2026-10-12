# Bee Researcher

Private-access news collection, AI relevance assessment, review and scheduled
publication. The source repository is public; application access is not.

## Repository layout

- `src/market_intelligence/app`: Researcher API, Admin/User/Report portals and pipeline.
- `src/market_intelligence/tests`: unit and contract regression tests.
- `src/market_intelligence/scripts`: isolated SQL/browser acceptance suites.
- `docs`: product/integration documents and release notes.
- `ops/security-hardening`: the one-time 3.39 security migration and rollback.
- `ops/scoped-release`: subsequent application-only, digest-bound cutovers.

The service version is defined in `src/market_intelligence/VERSION`. Read the
[service guide](src/market_intelligence/README.md) and
[3.41.0 release notes](docs/RELEASE-v3.41.0-fa.md) before running it.

## Private company reports

`/report` accepts unpublished company news using the same sign-in mechanism as
`/user`, but with independent sessions and explicit business/project grants.
The Owner configures Reporter/Business Manager access in Admin's Accounts and
access section. A Business Manager must consent to the AI data policy before
external analysis. Reports never enter the public news or publication pipeline.
See the [implementation and onboarding guide](docs/REPORT-PORTAL-IMPLEMENTATION-fa.md)
for scope, limits, encryption, retention, provider disclosure and safe deployment.
No real account grant or business consent is created automatically.

## Reader research desk

The `/user` portal includes daily audio briefs, multi-report comparison, claim
review, optional business context, tracking/timelines, bounded trend signals,
personal attention controls, action drafts, decisions, searchable/selectable
memory, explicit result sharing and personal cost/quality views. See the
[reader guide](docs/READER-RESEARCH-WORKSPACE-fa.md) for behavior and limits.

## Release safety

Use a branch and Pull Request. The Market Intelligence workflow requires unit,
static-analysis, dependency/image-security, browser and real SQL acceptance
gates. Only `main` can promote the exact scanned image to GHCR, sign its digest,
attest its SBOM and bind it to the source commit. Deployment must independently
verify that signature and binding; never deploy a mutable `latest` tag.

`ops/security-hardening/release.py` is **not** the general update command: its
3.39.0 migration rotates keys and moves credentials/Redis. For subsequent
updates, use the scoped controller after verifying the candidate and reviewing
the expected current revision. It never runs migrations, changes credentials,
resets sessions or restarts Contenter/Consultant/other Docker services.

Production secrets, database exports, logs and release artifacts are not source
code and must never be committed. Keep credentials in protected secret files;
do not put tokens in Git URLs, documents, screenshots, Sheet cells or issues.

Contenter is a separate application. Researcher uses its authenticated read-only
business API; do not share its database tables or automatically attach projects.
WhatsApp and mandatory Owner MFA remain paused by product decision.
