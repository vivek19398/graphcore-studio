# Local data workspace: first implementation

This increment implements the CSV portion of DATA-01/XLS-01 and the first guided data workflow. It is local development work and is not yet published to PyPI.

## Use it

1. Start Studio from the updated checkout and open the HTTP URL it prints.
2. Open **Data workspace** in the sidebar.
3. Click **Choose CSV** and select a UTF-8 comma-separated file with a header row.
4. Review the sample values and select a type for each column: Text, Whole number, Decimal (exact), or True / false. Columns start as Text. Click **Import table**, then choose **Preview / use**. Import errors identify the row and column; correct the type and retry without reselecting the file.
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

With `amount` selected as Decimal (exact), `amount` produces sum `0.30`, count 2 and null count 1. Decimal values are JSON strings to avoid binary floating-point rounding; the numeric schema identifies their meaning.

## Data contract and implementation

`studio/tables.py` owns the immutable local artifact store. CSV imports parse into bounded typed records and persist under `<Studio data directory>/tables/<sha256>.json`. The artifact ID hashes the complete stored content. Reads verify that content still matches its ID. Re-importing identical content and filename reuses the artifact. Importing different content creates a different ID, preserving existing workflow references.

Workflow state contains a `table_ref` with ID, filename, row count, column schema and original UTF-8 source hash. Full rows stay in the artifact file. Previews return at most 20 rows. Summary results carry the resolved source metadata. C++ schedules graph transitions; Python parses CSV and computes with `Decimal` at sufficient precision for the accepted bounds.

Inputs accept string, integer, decimal and boolean declarations. Empty cells become null. Booleans accept `true`/`false` without regard to case. Headers must be unique and nonempty. Incorrect row widths, incompatible values, unknown declared columns and nonfinite decimals fail with actionable errors. Import supports a UTF-8 BOM. It does not infer dates, currencies or locale-specific separators.

Limits: 2 MiB per source, 20,000 rows, 100 columns, 100 artifacts per workspace. Integers accept at most 100 digits; decimal inputs accept at most 100 characters with adjusted exponent within ±100 and stored exponent within ±200. Summation precision adapts to the accepted values. Artifacts intentionally have no delete operation in this increment, so existing checkpoint references remain valid. These are bounded local files rather than a database for large-scale analytics.

HTTP APIs use the existing local Host checks and write token:

- `POST /api/tables/inspect`: `{name, text}` → headers, up to five sample rows and row count; validates without persisting an artifact.
- `POST /api/tables`: `{name, text, types}` → `{table: table_ref}`.
- `GET /api/tables`: `{tables: [table_ref, ...]}`.
- `GET /api/tables/<id>`: metadata plus bounded `rows` and `truncated`.

## Validation and remaining delivery work

Automated coverage checks exact decimal results, nulls, invalid headers/types/rows, path rejection, tamper detection, deduplicated imports, preview caps, native node execution and actual HTTP import → run → result. JavaScript syntax is checked. Browser import → preview → generated workflow → run was verified locally on October 3. Cross-platform release builds are still required before publication.

Next increments:

1. XLSX sheet selection and new-workbook export, formula-cache warnings.
2. Deterministic filter, grouping, joins and reconciliation with explicit key and duplicate policies.
3. Versioned connector contract and a read-only parameterized SQL Server connector with bounded queries.
4. SQLite run/step/artifact metadata and immutable per-run configuration snapshots.
5. Bounded model/tool agent execution, budgets and meaningful usage/timing telemetry.
6. External action preparation, exact-payload approvals, durable action ledger and recovery tests before Outlook send.

This first increment does not implement the full enterprise specification, external connectors, workbook editing, team identity or remote deployment.

## Filter a table before calculating

Add a **Table filter** node between Input and Data summary. Choose the table reference field (`table`), an exact column name (`amount`), a comparison (`At least`), and a value (`0.2`). Set its output field to `filtered`; configure Data summary to read `filtered`. For values 0.1, 0.2 and 0.3 this produces an exact sum of `0.5`.

Supported comparisons: equals / does not equal for all types, greater / at least / less / at most for numeric columns, contains for text, and explicit Is null / Is not null. Text comparisons are case-sensitive. Enter comparison values as text; conversion follows the declared column type. Decimal comparisons are exact. Empty comparison values are rejected; use a null operator for empty CSV cells. Null cells never match ordinary comparisons, including Does not equal.

Filtering writes a new immutable artifact with the original column schema and row order, leaving the source unchanged. Its reference includes provenance (parent artifact ID, operation, column, operator, comparison value, source row count and matched count). Identical operations on the same artifact reuse the same ID. Zero matches return an empty table with its schema; a later summary reports sum `0`, count 0 and null min/max. The existing 100-artifact workspace cap also applies to derived tables. Chain filter nodes for multiple required predicates; OR groups and expressions are not implemented in this increment.

JSON node configuration:

```json
{"id":"filter","type":"data_filter","config":{"input_field":"table","column":"amount","operator":"gte","value":"0.2","output_key":"filtered"}}
```

Operator IDs are `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `contains`, `is_null`, `not_null`. Null operators do not require `value`.

## Grouped aggregation

Add **Grouped summary** after Input or Table filter. Set the table reference field, group column, numeric column, null-key policy and maximum groups (default 100, maximum 500). The output is another immutable `table_ref`, not a list of records in workflow state. Preview it in Data workspace, filter it, or pass it to Data summary using numeric column `sum` to calculate the grand total.

Each group produces:

| Column | Meaning |
|---|---|
| `group_key` | First encountered representation of the source key, retaining its declared type |
| `row_count` | All rows in the group |
| `count` | Non-null numeric values |
| `null_count` | Null numeric values |
| `sum` | Exact decimal total as a string |
| `min`, `max` | Exact decimal values, or null when no numeric values exist |

Groups retain their first-seen order. Text keys are case-sensitive. Decimal keys group by numeric equality, so 0.10 and 0.1 belong together. Include null keys as a separate group or exclude those rows; provenance records the excluded count. All-null numeric groups have sum `0` and null min/max. Empty input produces an empty grouped table with the complete schema. If the configured group limit is exceeded, execution fails without persisting a partial grouped result.

Example: team A has 0.1 and 0.2, team B has 0.4. Grouping produces sums `0.3` and `0.4`; summarizing the grouped `sum` column returns `0.7`. Only one group column and one numeric column are supported in this increment; multi-key grouping, averages and custom aggregate expressions remain future work.

```json
{"id":"group","type":"data_group","config":{"input_field":"table","group_column":"team","column":"amount","null_keys":"include","max_groups":100,"output_key":"grouped"}}
```

## Reconcile two tables

Import both CSVs with explicit column types. For each source, open **Preview / use**, set **Workflow input name** to `left` or `right`, and click **Use as workflow input**. Named references let you keep multiple tables in one workflow. Reusing an input name replaces that reference.

Add a **Table reconciliation** node. Map the two state fields, key columns and value columns explicitly (column names may differ). Connect to Output and render `{{comparison.summary}}`, using the configured output field name. The result contains `table` (an immutable reference) and `summary` (bounded status counts); full comparison rows remain in the artifact store. A Table filter can read `comparison.table`, filter `status` equals `changed`, and pass the result to a review/model node later.

| Output column | Meaning |
|---|---|
| `key` | Compared key; numeric keys use an exact decimal representation |
| `left_value`, `right_value` | Mapped values, with numeric values represented as exact decimal strings |
| `left_present`, `right_present` | Whether a source row exists, independently of null values |
| `status` | `matched`, `changed`, `left_only`, or `right_only` |
| `delta` | Exact left minus right for two non-null numeric values; otherwise null |

Rows follow left-key first appearance, then right-only key first appearance. Text equality is case-sensitive; numeric columns compare by exact value. Mapped types must match or both be numeric (integer/decimal). Both-null mapped values count as matched; one-null versus non-null is changed. Missing rows remain distinct from present rows containing null.

Duplicate policy defaults to **Fail on duplicates**. Explicit alternatives select the first or last source row for each key; summary/provenance records duplicate counts. Null keys default to failure, with explicit exclusion available and excluded-row counts recorded. The maximum result size defaults to 10,000 rows and can be set up to 20,000. Limit, duplicate, type and null-key failures do not persist a partial reconciliation artifact. Provenance records both parent IDs and mappings. Repeating the same operation reuses its artifact.

```json
{"id":"compare","type":"data_reconcile","config":{"left_field":"left","right_field":"right","left_key":"id","right_key":"code","left_column":"amount","right_column":"total","duplicates":"reject","null_keys":"reject","max_rows":10000,"output_key":"comparison"}}
```

This increment supports a single key and single compared value per side. Composite keys, multi-column comparisons, tolerances, fuzzy matching and writing changes back to either source are not implemented.
