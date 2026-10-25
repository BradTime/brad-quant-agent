# M6 Champion–Challenger Operations

Status: M6 complete.

## Forward-only lifecycle

A trusted `validated` prediction model is enrolled with 1–20 PIT-eligible
symbols. At each latest materialized close, the worker first creates an
immutable Signal Commitment containing feature preimages, forecasts, model
artifact/data hashes, universe manifest, industry vintages, regime evidence,
signal bars, portfolio state and targets. No label-session snapshot may exist.

After the next session is materialized, settlement verifies the commitment,
recomputes every source hash, and applies next-open fills with T+1 holdings,
100-share lots, 1% signal-volume participation, price limits, 10bp slippage,
commission and historical stamp tax. Missed commitments cannot be backfilled.

## Gates

The state sequence is:

1. 60 consecutive simulation sessions.
2. Reset Challenger and comparator to equal cash.
3. 20 consecutive shadow sessions against the current Champion; before the
   first Champion exists, the fixed comparator is cash.
4. `eligible_for_small_capital`.

Returns, excess return, Sharpe, drawdown and exposure-weighted daily direction
accuracy are recomputed from immutable observations. Shadow promotion also
requires the one-sided 95% lower bound of paired daily excess returns to exceed
zero. Probability calibration and interval coverage remain the OOS model
registry gates; M6 does not invent portfolio probabilities from constituent
forecasts.

## Attestation and rotation

Commitments, settlements and transition-chain links use HMAC-SHA256 with a
dedicated production key. The program pins the key ID. Keep prior `id=key`
entries configured during rotation; raw key material must differ from JWT,
Fernet and every other attestation key.

Promotion ignores mutable counters as evidence and independently verifies
exactly 60+20 continuous commitments, settlement links, timing, signatures,
artifact binding, transition path and recomputed statistics.

## Behavior attribution

Human overrides and original strategy targets are replayed from the same
server account state with the same execution constraints. The resulting delta
and behavior flags are append-only. A malformed record receives isolated
backoff/failure state and cannot block later users.
