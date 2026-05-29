---
name: dataproduct-exampledata
description: Extract a small sample of rows from a Databricks output port via a non-production SQL warehouse, scrub anything classified as PII or sensitive in the data contract, and upload the scrubbed sample to Entropy Data via the entropy-data CLI. Trigger when the user asks to "upload example data", "publish sample rows for the data product", or "give consumers a preview of the data".
---

# Upload example data for a data product

Sample rows let prospective consumers evaluate a data product without requesting access. This skill pulls a small sample from a non-production source via a Databricks SQL warehouse, scrubs sensitive columns, and uploads the result.

## How to run this skill

### Plan announcement (before Step 0)

Before running Step 0, print this plan to the user verbatim:

> Running **dataproduct-exampledata**. I'll:
> 1. Pre-checks: Databricks bundle, ODCS files, `entropy-data` CLI, `databricks` CLI authenticated, a non-prod SQL warehouse and catalog.
> 2. Identify the output port and its contract.
> 3. Build a scrub plan — drop PII/sensitive columns, hash IDs, drop free text. **Wait for your confirmation.**
> 4. Extract ~20 sample rows via `databricks sql query` against the non-prod target.
> 5. Build the example-data YAML and show the first rows. **Wait for your confirmation.**
> 6. Upload via `entropy-data example-data put`.
> 7. Summarize what was uploaded, what was scrubbed, and cleanup options.

Then proceed.

### Step 0 — Pre-checks

- Confirm `databricks.yml` exists at the working directory root (this is a Declarative Automation Bundle).
- Confirm there is at least one output-port ODCS file under `src/output_ports/`.
- Confirm `uv run --quiet entropy-data --version` succeeds from the project root. If it fails, run `uv sync` and retry; if still missing, stop and tell the user to verify `entropy-data` is listed in `pyproject.toml`'s `[dependency-groups].dev`. Use `uv run entropy-data …` for every CLI invocation in this skill.
- Confirm `databricks --version` is on PATH and `databricks auth describe` succeeds. If not, stop and tell the user to run `databricks auth login --host <host>`.
- Confirm a non-production target is available. Read `databricks.yml` `targets:` and pick a target whose `mode:` is `development` or whose catalog is clearly non-prod (e.g. `<user>_dev`). **Never use a `prod` target in this skill.** If only a prod target exists, stop and tell the user to add a dev target first.
- Identify a SQL warehouse to query against. Order of preference: (a) a `--warehouse-id` the user supplies, (b) the `warehouse_id` declared on the chosen target in `databricks.yml`, (c) the first warehouse from `databricks warehouses list -o json` that is running. If none is available, stop and ask the user to start one.

### Step 1 — Identify the output port

If multiple output ports exist, ask which one. For each candidate, you need:

- `OUTPUT_PORT_ID` (from `<id>.odps.yaml`)
- the matching `src/output_ports/v<N>/<file>.odcs.yaml`
- the table name and server config the contract points at — for Databricks, this is `catalog.schema.table` from the server block

### Step 2 — Build the scrub plan

Read the contract's field list. For each field, decide what to do with it:

| Contract signal | Action |
|---|---|
| `classification: pii` (or `confidential`, `restricted`) | **Drop the column** from the sample |
| Field name matches obvious PII patterns (`email`, `phone`, `ssn`, `passport`, `dob`, `birth_date`, `iban`, `address`, `name`, `first_name`, `last_name`) and no classification | Treat as PII, drop unless the user explicitly opts in |
| `tags` containing `pii` / `sensitive` / `gdpr` | Drop |
| Numeric ID that could be a customer/user identifier | Hash with a one-way function and prefix `sample_` (use Spark SQL `sha2(cast(<col> as string), 256)`) |
| Free-text `comment`/`note`/`description` columns | Drop unless the user explicitly opts in (free text often leaks PII not declared in the contract) |
| Everything else | Keep |

Show the user the scrub plan as a table — column → action — and **wait for confirmation before extracting any data.**

### Step 3 — Extract the sample

Build the SQL against the non-prod catalog from Step 0. Use Unity Catalog three-part naming:

```sql
select <kept-and-hashed-columns>
from <catalog>.<schema>.<table>
limit <N>;
```

Default `N = 20`. Preferred extraction methods, in order:

1. **`databricks api post /api/2.0/sql/statements`** — primary path. Works on every supported Databricks CLI version. Body shape:

   ```json
   { "warehouse_id": "<id>", "statement": "<sql>", "wait_timeout": "30s" }
   ```

   With `wait_timeout: "30s"` (the API's maximum synchronous wait), most statements return inline. If `.status.state` is `SUCCEEDED` after the POST, read rows from `.result.data_array`. If it returns `PENDING` or `RUNNING`, poll `databricks api get /api/2.0/sql/statements/<statement-id>` every 2s until terminal (`SUCCEEDED` / `FAILED` / `CANCELED`); cap at 5 minutes.

   Column metadata for naming is at `.manifest.schema.columns[].name` (matches the SELECT order).

2. **`databricks sql query`** — optional alternative if your CLI version (≥ 2.x roadmap) ships this subcommand. Returns the same JSON shape so the post-processing is identical. Skip and use method 1 if it errors with "unknown command".

3. **Manual fallback** — if both fail, paste the SQL into the user's hands and ask them to run it in a workspace SQL editor and paste the results back.

Convert the result rows into a list of objects keyed by **the contract column names** (the names that will be visible to consumers, not the warehouse aliases). Hold the rows in memory as `ROWS` for the next step — do not write a CSV. The `entropy-data example-data put` command takes a JSON or YAML body, not a CSV.

### Step 4 — Build the example-data document and show the sample

Construct the document the CLI expects (shown as YAML; JSON with the same keys is equally valid and is the default this skill writes — see below):

```yaml
id: <DATA_PRODUCT_ID>-<OUTPUT_PORT_ID>
dataProductId: <DATA_PRODUCT_ID>
outputPortId: <OUTPUT_PORT_ID>
dataContractId: <CONTRACT_ID>
schemaName: <model name from the ODCS schema/models block>
data:
  - { <col>: <val>, ... }   # one entry per row from ROWS
  - ...
```

Field semantics confirmed against `entropy-data example-data list -o json`: the ID convention is `<dataProductId>-<outputPortId>`; `schemaName` is the contract's top-level schema/models key (the table name as the contract names it).

Write the document to `examples/<DATA_PRODUCT_ID>-<OUTPUT_PORT_ID>.json` (create `examples/` if missing; add `examples/` to `.gitignore` if absent). **Default to `.json`** so the script needs only Python's stdlib (`import json`); the init template's `pyproject.toml` does not pin `pyyaml` as a dev dep. If the user explicitly asks for YAML output, write `.yaml` instead — but then ensure `pyyaml` is available first via `uv add --group dev pyyaml`.

Print the first 5 rows of `data:` in a Markdown table. Re-state the dropped columns. **Wait for explicit user confirmation before uploading.**

### Step 5 — Upload via entropy-data CLI

```
entropy-data example-data put <DATA_PRODUCT_ID>-<OUTPUT_PORT_ID> \
  --file examples/<DATA_PRODUCT_ID>-<OUTPUT_PORT_ID>.json
```

Notes on the CLI shape (verified against `entropy-data example-data put --help`):

- The example-data ID is a **single positional argument**, not `--data-product` / `--output-port` flags. By convention it is `<dataProductId>-<outputPortId>`; this must also match the `id:` field inside the document.
- `--file` accepts JSON or YAML, or `-` for stdin.
- `put` is upsert — running it again replaces the previous sample for that id.

If the CLI errors, surface the actual error and the relevant `--help` output to the user — do not improvise a different command.

### Step 6 — Final report

End with this two-part recap. Use the shared `Status` enum (AGENTS.md § Final-report Status enum).

**Part 1 — outcome table.**

| Artifact | Status | Details |
|---|---|---|
| Output port | already present | `<DATA_PRODUCT_ID>/<OUTPUT_PORT_ID>` |
| Scrub plan | … | `<dropped-count>` dropped, `<hashed-count>` hashed, `<kept-count>` kept |
| Sample extraction | … | `<rows>` rows via `databricks sql query` (warehouse `<warehouse-id>`, catalog `<catalog>`) |
| Example-data file | … | `examples/<DATA_PRODUCT_ID>-<OUTPUT_PORT_ID>.json` (or `.yaml` if explicitly chosen) |
| Upload to Entropy Data | … | `entropy-data example-data put` succeeded (upsert) |

**Part 2 — next steps.** Bullet list:

- Audit trail: list every column that was dropped or hashed inline so the user has a record of what's now visible to consumers.
- Local cleanup: offer to delete `examples/<DATA_PRODUCT_ID>-<OUTPUT_PORT_ID>.{json,yaml}` if it contains anything the user doesn't want left on disk.
- Visibility: the sample is now visible in Entropy Data under this data product (running the skill again upserts the same id and overwrites the previous sample).

If there is nothing additional to surface, write a single line: `No further action required.`

## Constraints

- **Hard guardrail: never upload columns classified as PII/sensitive in the contract, and never upload free-text columns by default.** This rule does not bend for "just this once" — the user can override per-column in Step 2, but the default must be drop.
- **Never use a production target** to extract the sample. Use a dev/test target only. If only prod exists, stop and tell the user to add a dev target first.
- **No silent uploads.** Steps 2 and 4 both require explicit user confirmation before progressing. Skipping either is a bug.
- **Don't commit the sample body** (JSON or YAML). `examples/` belongs in `.gitignore`. The uploaded copy is the system of record.
- **Idempotent re-runs are fine** — `entropy-data example-data put` is upsert and will overwrite the previous sample for the same id (`<dataProductId>-<outputPortId>`). Mention this in the final report so the user knows the prior sample is gone.
