# Hourly development sessions

Requested October 3, 2026. Execution environment is pending: the scheduling tool in this chat supports desktop/local execution, not provisioning a persistent cloud worker.

## Session contract

Run once per hour, with one focused feature increment or bug fix per session. Aim for 20–30 minutes of work; leave remaining time for validation and a durable handoff. Do not overlap active development sessions.

At the start, inspect the repository status, previous session notes, current product specification and account usage. Never discard existing work. If account usage cannot be read, ordinary usage is disallowed, or either applicable reported usage window is at least 60% consumed, defer development until a later scheduled session. Check again before implementation and before costly verification. If the threshold is reached, save progress and stop development for that session. Scheduled checks and work already in flight can themselves consume usage; this is a best-effort development threshold, not an enforceable account-wide quota cap. Other chats share account usage.

Use a configured economical model for routine sessions when supported by the chosen environment. Do not promise automatic model switching or a new quota by switching models. A separately billed API runner needs its own monetary budget; its API usage is not measured by the desktop account percentages.

## Initial sequence

1. Verify the current CSV data workspace in a browser and fix observed defects. Recheck packaging inclusion for new modules.
2. Replace JSON-only column declarations with guided type controls and actionable import feedback.
3. Add bounded deterministic filtering, with null/type semantics and targeted tests.
4. Add grouping and exact decimal aggregation, with provenance and limits.
5. Add table reconciliation with explicit key mappings and duplicate policies.
6. Add XLSX import with sheet/header selection and cached-formula warnings.
7. Add export to a new workbook, with deterministic contents and tests.
8. Introduce versioned connector contracts and read-only connector fixtures.

Treat this as an ordered queue of small deliverables, not a guarantee that each feature finishes in one hour. Split work when necessary and finish the current item before starting another.

## Validation and Git delivery

Run focused tests that establish the changed behavior, followed by the required regression checks. For UI changes, verify the actual browser interaction when available. Record skipped checks and reasons. Never claim a feature is complete when required validation failed.

Commit only relevant reviewed changes and push passing increments to a `codex/` development branch on the configured GraphCore repository. Preserve user changes and inspect staged content for credentials and generated data. Do not force-push, merge into the default branch, publish to PyPI or create cloud resources as an incidental part of a session. Save incomplete work and failures without presenting them as verified increments.

## Durable handoff

Maintain a session log containing: backlog item, outcome, changed files, validation results, branch/commit where applicable, unresolved issues, next concrete step and latest available usage percentages. Notify the user only for meaningful completion, failure or required input. Stay quiet for unchanged or deferred sessions.

## Environment choices

- Desktop heartbeat: available here; requires the computer and app to remain running. Uses the current chat context.
- Cloud worker: requires an accessible cloud execution environment and an authenticated runner. API-backed execution needs a separately approved spend budget. Cloud scheduling has not been configured by this plan.
