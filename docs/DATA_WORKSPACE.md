# Local data workspace: first implementation

This increment implements the CSV portion of DATA-01/XLS-01 and the first guided data workflow. It is local development work and is not yet published to PyPI.

## Use it

1. Start Studio from the updated checkout and open the HTTP URL it prints.
2. Open **Data workspace** in the sidebar.
3. Enter column declarations, for example `{"amount":"decimal","quantity":"integer","active":"boolean"}`. Undeclared columns are strings. Use `{}` for an all-text import.
4. Click **Import CSV**, select a UTF-8 comma-separated file with a header row, then choose **Preview / use**.
5. Click **Build summary workflow** to create Input → Data summary → Output. This replaces the canvas through its existing replacement flow. The first numeric column is selected; change it in the node inspector if needed.
6. Click **Run workflow**. No API key or model is needed. The result contains count, null count, exact decimal sum, minimum, maximum, and source metadata.

Alternatively use **Use as workflow input “table”** in an existing workflow, add a Data summary node, set its input field to `table`, set the numeric column name, and connect its next output. Refer to `{{summary.sum}}` or `{{summary}}` from a later model or output node, using your configured output field name.

Example file:

```csv
customer,amount,quantity,active
Acme,0.10,2,true
Beta,0.20,3,false
Gamma,,1,true
```

With the declarations above, `amount` produces sum `0.30`, count 2 and null count 1. Decimal values are JSON strings to avoid binary floating-point rounding; the numeric schema identifies their meaning.

## Data contract and implementation

`studio/tables.py` owns the immutable local artifact store. CSV imports parse into bounded typed records and persist under `<Studio data directory>/tables/<sha256>.json`. The artifact ID hashes the complete stored content. Reads verify that content still matches its ID. Re-importing identical content and filename reuses the artifact. Importing different content creates a different ID, preserving existing workflow references.

Workflow state contains a `table_ref` with ID, filename, row count, column schema and original UTF-8 source hash. Full rows stay in the artifact file. Previews return at most 20 rows. Summary results carry the resolved source metadata. C++ schedules graph transitions; Python parses CSV and computes with `Decimal` at sufficient precision for the accepted bounds.

Inputs accept string, integer, decimal and boolean declarations. Empty cells become null. Booleans accept `true`/`false` without regard to case. Headers must be unique and nonempty. Incorrect row widths, incompatible values, unknown declared columns and nonfinite decimals fail with actionable errors. Import supports a UTF-8 BOM. It does not infer dates, currencies or locale-specific separators.

Limits: 2 MiB per source, 20,000 rows, 100 columns, 100 artifacts per workspace. Integers accept at most 100 digits; decimal inputs accept at most 100 characters with adjusted exponent within ±100 and stored exponent within ±200. Summation precision adapts to the accepted values. Artifacts intentionally have no delete operation in this increment, so existing checkpoint references remain valid. These are bounded local files rather than a database for large-scale analytics.

HTTP APIs use the existing local Host checks and write token:

- `POST /api/tables`: `{name, text, types}` → `{table: table_ref}`.
- `GET /api/tables`: `{tables: [table_ref, ...]}`.
- `GET /api/tables/<id>`: metadata plus bounded `rows` and `truncated`.

## Validation and remaining delivery work

Automated coverage checks exact decimal results, nulls, invalid headers/types/rows, path rejection, tamper detection, deduplicated imports, preview caps, native node execution and actual HTTP import → run → result. JavaScript syntax is checked. Browser import → preview → generated workflow → run was verified locally on October 3. Cross-platform release builds are still required before publication.

Next increments:

1. Typed column mapping controls, XLSX sheet selection and new-workbook export, formula-cache warnings.
2. Deterministic filter, grouping, joins and reconciliation with explicit key and duplicate policies.
3. Versioned connector contract and a read-only parameterized SQL Server connector with bounded queries.
4. SQLite run/step/artifact metadata and immutable per-run configuration snapshots.
5. Bounded model/tool agent execution, budgets and meaningful usage/timing telemetry.
6. External action preparation, exact-payload approvals, durable action ledger and recovery tests before Outlook send.

This first increment does not implement the full enterprise specification, external connectors, workbook editing, team identity or remote deployment.
