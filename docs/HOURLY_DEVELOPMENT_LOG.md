# GraphCore development session log

## October 3, 2026 — CSV foundation verification

- Completed the first planned increment: verified browser import → preview → Build summary workflow → native execution. Synthetic fixture returned sum `0.3`, count 2 and null count 1.
- Fixed decimal rounding for wide exponent ranges by deriving aggregation precision from accepted values. Added numeric length/exponent bounds, including extreme zero-exponent rejection.
- Validation: 36 unit/compiler/Python tests and 8 loopback HTTP tests passed; JavaScript syntax check passed; fresh macOS 11 ARM64 wheel and source builds passed; archive inclusion and Twine checks passed.
- Browser evidence: `/tmp/graphcore-csv-browser-check.jpg`; test data isolated under `/tmp/graphcore-ui-check-oct3`.
- Delivery branch: `codex/local-data-foundation`. Commit and remote delivery are recorded by Git; see the session result in this chat.
- Existing implementation files for retrieval, onboarding and CSV were included as dependencies of this coherent increment. The user-authored product specification was left outside the commit.
- Artifacts still report already-released version 0.2.2 and must not be uploaded. Cross-platform CI and a release version bump remain pending.
- Usage checks: start 3% five-hour / 0% weekly; pre-implementation 5% / 1%, both below 60% consumed.
- Next step: replace JSON-only column declarations with guided column type controls and actionable import feedback. Retain the existing typed artifact contract and targeted tests.
