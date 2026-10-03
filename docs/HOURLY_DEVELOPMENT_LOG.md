# GraphCore development session log

## October 3, 2026 — CSV foundation verification

- Completed the first planned increment: verified browser import → preview → Build summary workflow → native execution. Synthetic fixture returned sum `0.3`, count 2 and null count 1.
- Fixed decimal rounding for wide exponent ranges by deriving aggregation precision from accepted values. Added numeric length/exponent bounds, including extreme zero-exponent rejection.
- Validation: 36 unit/compiler/Python tests and 8 loopback HTTP tests passed; JavaScript syntax check passed; fresh macOS 11 ARM64 wheel and source builds passed; archive inclusion and Twine checks passed.
- Browser evidence: `/tmp/graphcore-csv-browser-check.jpg`; test data isolated under `/tmp/graphcore-ui-check-oct3`.
- Delivery branch: `codex/local-data-foundation`. Implementation commit `ff19d06` was pushed successfully to origin. Repository-local Git identity now uses the existing GitHub no-reply identity for future commits; the implementation commit used the machine default identity.
- Existing implementation files for retrieval, onboarding and CSV were included as dependencies of this coherent increment. The user-authored product specification was left outside the commit.
- Artifacts still report already-released version 0.2.2 and must not be uploaded. Cross-platform CI and a release version bump remain pending.
- Usage checks: start 3% five-hour / 0% weekly; pre-implementation 5% / 1%, both below 60% consumed.
- Next step: replace JSON-only column declarations with guided column type controls and actionable import feedback. Retain the existing typed artifact contract and targeted tests.

## October 3, 2026 — Guided CSV column mapping

- Replaced JSON-only column declarations with Choose CSV → sample review → per-column type dropdowns → explicit Import table.
- Added a nonpersisting inspection endpoint with up to five sample rows; shared parsing keeps validation consistent with import.
- Added inline row/column errors, preserved choices after failed import, cleared outdated errors on type changes and strict browser UTF-8 decoding.
- Browser verified: select Whole number for fractional values → actionable error → change to Decimal → successful import. Final importer screenshot: `/tmp/graphcore-guided-import.jpg`.
- Validation: 37 unit/compiler/Python tests, 9 HTTP tests, JavaScript syntax and diff checks passed. No package dependencies or native core changes; no live model calls or PyPI release.
- Delivery: continuing on `codex/local-data-foundation`; corresponding feature commit is recorded in Git history.
- Usage: start 8% five-hour / 1% weekly; final check 12% / 2%, below the 60% threshold.
- Next step: bounded deterministic table filtering, with explicit null/type semantics, a canvas node and focused tests.

## October 3, 2026 — Deterministic table filtering

- User explicitly requested continuation after the below-50% stop rule; this interactive session resumed while the hourly automation rule remains unchanged.
- Added Table filter canvas node with typed comparison forms, explicit null controls and immutable derived artifacts carrying immediate parent provenance.
- Filtering preserves source rows/schema and order, supports exact decimal comparisons, rejects incompatible operators/types and reuses identical derived artifacts.
- Validation: 39 unit/compiler/Python tests and 9 HTTP tests passed (48 total), including null semantics, numeric ordering, boolean/text matching, invalid configs, empty results and native filter → summary execution. JavaScript syntax and diff checks passed.
- Actual browser verified inspector null/value controls and full workflow result `Filtered total: 0.5`; screenshot `/tmp/graphcore-filter-result.jpg`.
- Delivery continues on `codex/local-data-foundation`; no default-branch merge or PyPI publication.
- Usage at start: 13% five-hour / 2% weekly. User's explicit continuation authorized this session at that usage.
- Next step: grouping and exact decimal aggregation with bounded output and clear null/group-key semantics.

## October 3, 2026 — Grouped exact aggregation

- Continued under the user's explicit interactive resume; hourly scheduling retains its separate below-50% stop rule.
- Added Grouped summary canvas node, per-group exact statistics and immutable typed grouped table references with parent provenance.
- Defined first-seen order, case-sensitive text keys, decimal key numeric equality, include/exclude null-key policy and all-null/empty-input behavior.
- Default group cap 100, configurable up to 500; overflow fails before persisting partial results. Derived previews retain provenance when reused as workflow inputs.
- Validation: 43 unit/compiler/Python tests and 10 HTTP tests passed (53 total), covering exact totals, null statistics, order, decimal keys, limits/no partial artifacts and native/HTTP execution. Browser verified inspector and `Groups: 2. Total: 0.7`; evidence `/tmp/graphcore-group-result.jpg`.
- No native runtime changes, dependencies or live model calls. Delivery remains `codex/local-data-foundation`; no PyPI release.
- Usage at start 18% five-hour / 3% weekly.
- Next step: table reconciliation with explicit key mapping and duplicate policies, then XLSX support.

## October 3, 2026 — Explicit table reconciliation

- Resumed under the user's interactive continuation. Implemented one-key/one-value full outer reconciliation with explicit mappings, typed equality and exact left-minus-right decimal deltas.
- Added duplicate reject/first/last policies, null-key reject/exclude policies, status counts and row bounds. Missing rows are distinguished from present rows with null values. Results retain both source artifact IDs and mappings.
- Added named table-reference inputs in Data workspace; browser verified adding `source_left` preserved other references.
- Validation: 46 unit/compiler/Python tests plus 11 HTTP tests passed (57 total), including numeric cross-type keys, mapped column names, duplicate/null policies, no partial writes, native delta summary and HTTP preview. JavaScript syntax and diff checks passed.
- Browser verified inspector controls and `Changed: 1. Left only: 1. Right only: 1.`; evidence `/tmp/graphcore-reconciliation-result.jpg`.
- Delivery remains the existing development branch, with no live provider calls or PyPI publication.
- Start usage: 22% five-hour / 3% weekly. Interactive resume does not change the scheduled below-50% stop rule.
- Next step: XLSX support with sheet selection, typed import and formula-cache warnings; research the implementation dependency before adding it.
