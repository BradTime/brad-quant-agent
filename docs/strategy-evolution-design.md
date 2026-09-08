# Strategy Evolution and Adversarial Decision Design

Status: milestone 1 implementation baseline
Protocol: `signal-v1`

## 1. Safety boundary

The strategy subsystem produces research signals. It does not bypass portfolio
construction, the deterministic risk officer, broker permissions, programmatic
trading registration, or human kill switches.

Public chat remains research-only. Explicit orders may only be produced inside
the authenticated private decision room after the relevant strategy has passed
the promotion state machine. Live Eastmoney connectivity must use official
EMT/GM channels; browser automation, cookies and unofficial order endpoints are
not supported.

## 2. Immutable strategy definition

`strategies` remains the mutable user-facing head record. Every executable
definition is copied to an append-only `strategy_versions` row:

- tenant and parent strategy ID
- monotonically increasing version
- `builtin` or `custom_python` definition type
- category, built-in implementation type and normalized parameters
- normalized source for custom strategies
- `signal-v1` protocol version
- executor implementation version (`builtin-v1` / `sandbox-signal-v1`)
- SHA-256 over the complete canonical definition
- creation timestamp

Renaming or editing a description does not create a version. Any semantic
change to implementation type, parameters or source creates a new version and
returns the strategy to `draft`. Historical versions are read-only through the
service and API. Deleting a strategy tombstones its head; version rows remain
available to the audit store for the one-year retention period.

## 3. Signal protocol

Built-in and custom definitions return the same JSON-compatible envelope:

```json
{
  "schemaVersion": 1,
  "protocolVersion": "signal-v1",
  "signals": [
    {
      "code": "600000.SH",
      "score": 0.5,
      "confidence": 0.8,
      "reason": "human-readable bounded evidence"
    }
  ]
}
```

`score` is a directional research score in `[-1, 1]`; it is not an order or
target weight. `confidence` is in `[0, 1]`. Portfolio sizing and risk checks are
separate deterministic stages. This separation prevents custom code from
choosing leverage or bypassing account limits.

The first adapters cover the four existing built-ins (dual moving average,
RSI, Bollinger and momentum). Milestone 2 expands the catalog without changing
the protocol and pins versions into capacity-aware backtests. Milestone 1
exposes bounded signal execution at
`POST /strategies/{id}/versions/{version}/signals`; it does not present custom
strategies as compatible with the existing backtest form.

## 4. Restricted custom Python

Custom source must define exactly:

```python
def generate_signals(context, bars):
    return {"signals": []}
```

The accepted language is intentionally not general Python:

- no imports, attributes, classes, exceptions, lambdas, async, generators,
  dynamic code, I/O or top-level execution
- only bounded syntax and a small pure-function allowlist
- JSON-compatible inputs and normalized signal-only outputs
- strict source, AST, signal count, reason and output-size bounds
- child-side 1 MiB serialization cap before stdout reaches the parent
- isolated Python process with sanitized environment and temporary working
  directory
- wall-clock timeout plus POSIX CPU, address-space, file-size, descriptor and
  child-process limits where the host supports them

The AST capability model is the primary boundary. OS resource limits are
defense-in-depth, not a claim that a generic Python subprocess is equivalent to
a hardened container. Before accepting third-party hostile code in production,
run the worker in a dedicated rootless container/microVM with read-only rootfs,
no network namespace, seccomp/AppArmor, dropped capabilities and no mounted
application secrets.

## 5. Milestone sequence

1. Immutable definitions, unified signal protocol and restricted sandbox.
2. Full-A-share daily strategy catalog and capacity-aware PIT backtests.
3. ML direction/quantile predictions, calibration, regimes and portfolio risk.
4. Researcher, falsifier, investment committee and deterministic risk officer.
5. Private decision room, WebSocket/Feishu alerts, MFA and kill switch.
6. Champion–Challenger simulation, shadow promotion and behavior attribution.
7. Official Eastmoney simulation adapter, reconciliation and filing evidence.
8. Conditional small-capital live activation.

Each milestone must preserve tenant isolation, append-only evidence, point-in-
time correctness and reproducibility by strategy/data/code version.

## 6. Milestone 2 progress

The first M2 slice adds four representative daily strategies to the original four:
Donchian breakout, cross-sectional momentum, z-score reversion, a deliberately
price/volume-only composite factor. Fundamental and event factors are not
approximated from price or mutable `(code, trade_date)` rows; they remain
blocked until append-only as-of panels are available.

Saved built-in strategies may be backtested with `strategyId` and
`strategyVersion`. The server resolves the immutable row and persists the
strategy/version IDs, protocol and definition SHA-256 both as indexed run
columns and in the configuration envelope.

`build-pit-universe` materializes daily full-A membership from historical bars,
effective-dated status and immutable listing dates. The strict defaults are:
120 listed sessions, 20 complete amount observations, average amount at least
RMB 50 million, normal PIT status, a traded bar and complete OHLC. Suspended,
ST and delisting states fail closed. The current command materializes one
explicit date per invocation.

Manual runs of at most 20 symbols can opt into
`universeMode=pit_filtered`. Membership must cover every XSHG session in the
requested range. Historical full-A `xs_momentum`/`composite_mf` runs use a
dedicated asynchronous executor: it queries fixed-size session chunks, retains
only bounded rolling fields, checks cancellation each day, heartbeats the job
lease, and never uses the per-symbol loader or retains five-year bars.
Rows are immutable within a rules version. A bounded filtered run stores its
exact daily membership map and SHA-256; a full-A run stores the verified daily
manifest hashes plus a combined hash, so later rules or data revisions cannot
silently rewrite the historical universe.

Every engine uses 10bp default slippage and limits a next-open fill to 1% of the
signal-day volume. Missing signal-day volume rejects the fill; a volume-capped
partial fill does not silently carry an oversized remainder. Result payloads
surface execution and universe quality counters.
