# Market Intelligence v2.4.0

## MI-021 — feedback ranking gate

- Approved feedback signal can now be applied through an authenticated admin endpoint.
- Minimum sample size is enforced (default 3 distinct feedback records).
- Per-topic adjustment is bounded to ±0.05 and scores remain in [0, 1].
- Idempotency is enforced through `JobRun`.
- The response records each changed topic, sample counts, vote direction and adjustment.
