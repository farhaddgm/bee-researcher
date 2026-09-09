# Bee CFO v2.79.0

## Scope

This release executes the approved phase-one proposals PF1-026, PF1-027 and
PF1-028:

- deterministic, evidence-linked factor attribution;
- multi-horizon numeric forecasts for 1, 7 and 30 days using a transparent
  baseline/trend/volatility ensemble;
- explicit insufficient-history `no_call` behavior;
- forecast evaluation and calibration metrics (MAE, MAPE, directional
  accuracy, interval coverage and Brier score);
- Telegram report sections for factors and numeric forecast ranges;
- isolated Bee CFO persistence and migration `0019_bee_cfo_factor_forecast`.

## Safety and separation

The feature uses the existing `SharedResearcherAdapter` only for public
fetching/extraction and keeps all new state in `bee_cfo_*` tables. It does not
read holdings, goals, risk profile or recommendations and does not alter Bee
Researcher tables, queues or UI.

## Verification

- Bee CFO contract, factor, forecast, delivery and isolation tests pass in the
  service container.
- Full Market Intelligence test suite passes.
- Migration head is `0019_bee_cfo_factor_forecast`.
- Live Telegram UAT and calibration with real price history remain operational
  checks for the configured workspace; the runtime fails closed until those
  inputs exist.
