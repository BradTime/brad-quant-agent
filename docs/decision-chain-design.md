# M4 Four-Layer Decision Chain

Status: M4 complete.

## Trust boundary

The chain consumes one immutable M3 authoritative-allocation decision. Clients
may submit only a latest materialized session and up to 20 canonical A-share
codes. They cannot submit probabilities, expected returns, account state,
industry, market regime, positions, limits, or risk results.

M4 never creates an order. Its strongest output is a risk-approved research
candidate with `executionApproved=false`.

## Stages

1. The researcher converts Champion forecasts and the authoritative allocation
   into direction probabilities, P10/P50/P90 intervals, target exposure,
   evidence references, no-trade conditions, stop/take-profit research
   boundaries, and maximum holding sessions.
2. The contrarian receives the same server evidence but not the researcher's
   claims. It independently applies conservative-tail and regime rules and must
   include a no-trade alternative.
3. The claims are revealed for exactly two structured cross-examination rounds.
4. The investment committee applies deterministic scoring and records why any
   contrarian concern was not adopted.
5. The deterministic risk officer has final veto power. It cannot loosen M3
   limits and cannot approve execution.

Direction conflict, expected-return gap above two percentage points, target
weight gap above 10% of equity, evidence mismatch, or committee confidence
below 60% is a severe disagreement.

## Audit and replay

Every stage is an immutable event containing the actor, sequence, input/output
hashes, previous-event hash, event hash, protocol version, and structured
payload. The event hash includes the previous hash, producing a per-run audit
chain. Runs and events retain immutable user-ID snapshots if an account is
deleted.

Run creation reserves a unique `(user snapshot, session, request hash)` before
calling M3, so retries cannot generate parallel chains for the same request.
