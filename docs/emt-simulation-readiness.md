# M7 Eastmoney Simulation Readiness

Status: foundation complete; official-terminal acceptance blocked.

The implementation follows the official Eastmoney/掘金 Python documentation
at `emt.18.cn` and imports only the terminal-provided `gm.api` SDK. Browser
automation, cookies, undocumented endpoints, and a PyPI substitute are not
used.

Implemented controls include:

- encrypted account/strategy bindings tied to append-only filing profiles and
  a source/config implementation fingerprint
- one active bridge lease per binding and the documented millisecond `timer`
  callback
- purpose-bound MFA for capped rehearsal intents, user-scoped idempotency,
  database rate windows, and at-most-once uncertain state after disconnect
- encrypted cash/position/order/execution snapshots, normalized order events,
  uncertain-send correlation, reconciliation mismatches and immutable event
  chains
- Kill Switch/account-deletion checks, filing revalidation, and append-only
  authorization-revocation events

## Explicit blocker

`MODE_LIVE` carries both simulation and live accounts. The public SDK docs
expose account ID and connection status but no machine-verifiable account-type
field. A confirmation string or account-name convention cannot prove that an
account is simulated.

Consequently `simulation_account_verified` is hard-coded false. The bridge is
read-only, staged orders remain `blocked_account_type`, and `order_volume` is
unreachable. Contract tests use a fake SDK but cannot create official rehearsal
evidence.

M7 may be accepted only after an official terminal/SDK supplies trustworthy
account-type evidence and a real simulation run demonstrates duplicate
suppression, rate limiting, disconnect recovery, clean cash/position/order/
execution reconciliation, and no live-account access.
