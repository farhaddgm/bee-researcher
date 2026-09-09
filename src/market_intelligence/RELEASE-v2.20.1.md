# Bee Researcher v2.20.1

## Stability patch

- Fixed pipeline clustering records that could miss `assistant_id` and fail scheduler runs with a database constraint error.
- Manual and scheduled pipeline execution now preserve workspace isolation for new event clusters and cluster members.
