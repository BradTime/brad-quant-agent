# M3 Prediction and Portfolio Design

Status: M3 core complete. Trusted model registry, operator training/inference,
and server-authoritative allocation are implemented.

## Prediction contract

The signal date is the market session whose close makes features visible. The
label is the immediately following XSHG session's open-to-close return. Missing
or suspended sessions are never bridged to a later bar. Every example stores
both `signal_date` and `label_date`.

Feature schema `daily-pit-v1` contains only current/prior HFQ price, range,
volatility, amount and volume transformations. Universe filtering uses only the
signal date; consulting label-date membership would leak future suspension/ST/
delisting state. The next bar must nevertheless be the immediately adjacent
XSHG session or the example is dropped.

Purged expanding-window folds use trading dates only. Training labels must end
before the embargo boundary; validation remains contiguous and ordered.
Random train/test splitting is prohibited.

## Models and metrics

M3 supports LightGBM and XGBoost adapters:

- binary next-day direction probability
- isotonic probability calibration fitted on a trailing calibration slice
- 10th, 50th and 90th return quantiles

Out-of-sample promotion gates are balanced accuracy at least 53%, expected
calibration error at most 10%, and 80% interval coverage between 75% and 85%.
Evaluation requires at least 100 samples. Promotion requires at least three
Purged OOS folds and at least 100 OOS samples in each of bull, bear, range and
risk-off, with every fold/regime report passing.

Artifacts are internal candidate files under `PREDICTION_ARTIFACT_DIR`.
LightGBM/XGBoost native model files, calibrator JSON and manifest have separate
SHA-256 values. The database reserves a model version before evaluation and is
the independent source of the manifest checksum. Verified file bytes are
copied to a private temporary directory before native parsing; pickle/joblib is
never loaded.

## Regime and portfolio boundary

`regime-rules-v1` classifies bull, bear, range and risk-off from 60-session
benchmark trend, realized volatility and market breadth. `/portfolio/regime`
is explicitly a non-authoritative preview because its inputs are user supplied.

The internal allocator enforces:

- equity no greater than RMB 200,000 and gross exposure no greater than 2x
- 20% single-name, 30% industry and 25% correlated-category risk pools
- predicted daily loss no greater than 2%
- 15% warning, 18% no-new-position and 20% force-reduce states

`/portfolio/authoritative-preview` accepts only codes and the latest materialized
session. In one PostgreSQL `REPEATABLE READ` transaction it locks the account
and positions, values them from that session's daily bars, and reads
first-observed PIT industry, Champion forecasts, benchmark, market breadth and
risk profile. It persists immutable user-ID snapshots plus input/output hashes.
Agents and clients may not submit those facts. The output explicitly keeps
`executionApproved=false`; backtest-to-simulation links to manual review.

## Operational follow-up

1. Add weekly, lease-protected retraining and inference jobs.
2. Add an admin model-run/OOS/calibration dashboard.
