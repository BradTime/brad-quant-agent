# M5 Private Decision Room

Status: M5 complete.

The authenticated decision room displays M4's six-stage evidence chain and
server risk state. It supports `research_only`, `manual_review`, and
`simulation_ready`; none enables order execution.

Sensitive actions consume a five-minute, one-time JWT backed by a locked
database grant and bound to exactly one purpose. Issuance requires the account
password plus replay-protected RFC 6238 TOTP. Ten high-entropy recovery codes
are shown once and stored only as hashes; they may only reset TOTP or authorize
account deletion. Reset removes all factors/grants and increments token version.

Kill Switch activation is immediate and does not require step-up. Release,
mode changes, overrides, and account deletion do. Overrides require a reason,
cannot revive a committee/risk veto, cannot add a symbol outside the risk
officer's approved set, and recheck single-name, industry, leverage, and
predicted-loss limits. They never create orders.

Severe disagreement, risk veto, and Kill Switch events are persisted before
delivery. Private WebSocket messages and Feishu alerts carry a stable
notification ID and only a redacted message plus in-app path. Delivery uses a
claim lease and capped exponential retries. Training artifact deletion likewise
uses encrypted, persistent post-commit outbox records so database rollback
cannot leave live rows pointing to prematurely removed files.
