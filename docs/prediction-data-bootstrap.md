# Prediction Data Bootstrap

Status: implemented and operationally verified.

The bootstrap uses Tushare Pro's trade-date bulk endpoints instead of
per-symbol requests. `daily` and `adj_factor` are paginated and validated before
writing. Tushare volume lots are converted to shares and amount thousands to
RMB.

For each session, bars and factors are upserted before an immutable manifest is
inserted in the same transaction. The importer reads persisted rows back,
normalizes database precision, and requires response/persistence counts and
hashes to match. PostgreSQL triggers then prevent inserts, updates, or deletes
for manifested stock dates. A manifest count mismatch is an integrity error,
not a reason to overwrite evidence.

Name/ST intervals are normalized into complete, non-overlapping timelines.
Daily suspensions come independently from fully paginated `suspend_d` rows.
Missing bars are accepted by ingestion audit only when an exact Tushare
suspension row exists; membership-derived `suspended` reasons cannot certify
their own missing input.

Universe membership uses `(code, trade_date, rules_version)` as its primary
key, allowing corrected rule/data versions to coexist. Readiness requires all
configured codes, at least 252 eligible sessions per code, valid bars and
factors on every eligible code/date, full benchmark coverage, and matching
ingestion watermarks.

The verified operating dataset contains 1,307 sessions. The ten-symbol research
pool has 1,277–1,288 eligible sessions per symbol and passes all five-year data
gates. This is data readiness only: evaluated LightGBM and XGBoost candidates
remain rejected because balanced accuracy is near 50%, below the fixed 53%
promotion threshold.
