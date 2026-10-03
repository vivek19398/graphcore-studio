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
