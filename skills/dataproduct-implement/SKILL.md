---
name: dataproduct-implement
description: Given an Entropy Data data product URL or id, fetch its data contracts (output port ODCS files written next to the Python under src/output_ports/v<N>/, input port ODCS files cached next to their Spark reader under src/input_ports/), translate the schema into Lakeflow @dp.materialized_view / @dp.table Python pipelines, and ensure the project has the publishing layer (ODPS, GitHub Actions). Trigger when the user asks to "implement the data product <url>", "build the Lakeflow pipeline for this data product", or "scaffold output-port tables from a data contract".
---

# Implement a data product from its data contract

Turn an Entropy Data data product into a working Lakeflow Spark Declarative Pipeline. The data contract (ODCS) is the source of truth for output schema; this skill reads it and writes the bundle artifacts that produce data matching the contract.

## When to use this vs. other skills

- **Empty directory, no bundle yet** → run `dataproduct-init` first, then come back here.
- **Existing bundle, need ODPS/ODCS/CI scaffolding only** → use `entropy-data-publish` instead.
- **Existing bundle, want to derive output-port table definitions from a published data contract** → this skill.

## How to run this skill

### Plan announcement (before Step 0)

Before running Step 0, print this plan to the user verbatim:

> Running **dataproduct-implement**. I'll:
> 1. Pre-checks: confirm this is a Databricks bundle, the `databricks` CLI is installed and authenticated, and the `entropy-data` CLI is connected.
> 2. Resolve the data product by id or URL (`entropy-data dataproducts get`).
> 3. Fetch each selected output port's data contract (`entropy-data datacontracts get`) and save it next to the Python it governs, under `src/output_ports/v<N>/`.
> 4. Validate the contract against Unity Catalog conventions (lowercase identifier folding). If fixable bugs are found, offer to patch and publish the corrected contract back to Entropy Data.
> 5. Translate the ODCS schema into Lakeflow Python files under `src/output_ports/v1/` — `@dp.materialized_view` for batch bodies (the default; the placeholder body and the typical UC-table-to-UC-table wiring are both batch), `@dp.table` only when the body uses `spark.readStream.table(...)`. Lists columns, types, and quality expectations.
> 6. Implement the pipeline bodies: cache each upstream contract under `src/input_ports/<provider-op-id>.odcs.yaml` as a trust snapshot, write `@dp.view` wrappers that read the upstream UC tables, and project from input columns to output columns (with confirmation; complex joins left as TODOs).
> 7. Stamp the data product on Entropy Data with the `dataProductBuilder` customProperty so the platform knows it is managed by this builder.
> 8. Hand off to `entropy-data-publish` to add any missing publishing artifacts (ODPS, GitHub Actions).
> 9. Summarize what was generated and the open TODOs.

Then proceed.

### Step 0 — Pre-checks

- Confirm `databricks.yml` exists at the working directory root. If not, ask whether to run `dataproduct-init` first, then stop.
- Confirm `databricks --version` is on PATH. If not, stop and tell the user to install the CLI (`brew install databricks/tap/databricks` on macOS).
- Confirm `databricks auth describe` succeeds. If not, stop and tell the user to run `databricks auth login --host <workspace-url>`.
- Confirm `uv run --quiet entropy-data --version` succeeds from the project root. If it fails, run `uv sync` (the init template seeds `entropy-data` as a dev dep) and retry. Once available, run `uv run entropy-data connection test`. If that fails, stop and tell the user to run `uv run entropy-data connection add <name> --host <host> --api-key <key>`. Use `uv run entropy-data …` for every CLI invocation in this skill.

### Step 1 — Resolve the data product

Accept either:

- a full URL (e.g. `https://app.entropy-data.com/dataproducts/<id>`) — extract the trailing id, **or**
- a bare data product id.

Run `entropy-data dataproducts get <id> -o yaml`. Remember the response as `DATA_PRODUCT`. Extract:

- `DATA_PRODUCT_ID`, `DATA_PRODUCT_NAME`, owning team, purpose
- the list of output ports — each has an id, a server (`catalog.schema.table` for Databricks), and a linked data contract id

If the data product has more than one output port, ask the user which one(s) to implement in this run. Default to all.

If `entropy-data dataproducts get <id>` 404s, try `entropy-data datacontracts get <id> -o yaml` next — the user may have given a contract id instead of a data product id (common when the spec started in the contract editor). If the contract resolves, treat the data product as not-yet-on-platform:

1. Remember the response as `CONTRACT` and derive `DATA_PRODUCT_ID` per the rule in AGENTS.md § Deriving `DATA_PRODUCT_ID` from a contract id; confirm with the user.
2. Treat the contract as the data product's single v1 output port. The output-port's catalog/schema/table come from `CONTRACT.servers[]` (first `type: databricks` entry) and the linked contract id is the contract's own `id`.
3. **Skip Step 2's fetch** — the contract is already in hand. Write it to `src/output_ports/v1/<CONTRACT.id>.odcs.yaml` (if absent) and jump to Step 2.5 with `CONTRACT` already populated and `<N> = 1`.
4. The first publish creates the data product on the platform; Step 5 detects the not-yet-on-platform state and skips the stamping push.

If neither lookup succeeds, ask the user if they want to create a new data product from scratch.

If any selected output port's `server.type` is not `databricks`, skip it with a warning. This plugin only generates Lakeflow code; for other platforms, use the matching builder.

### Step 2 — Fetch the data contracts

For each selected output port, run `entropy-data datacontracts get <contract-id> -o yaml` with the contract id from the data product. Remember the response as `CONTRACT`, and write it to `src/output_ports/v<N>/<contract-id>.odcs.yaml` (the version directory matches the output port's version — default `v1` if the data product does not declare one). If the file already exists and differs from the fetched contract, surface the diff and ask before overwriting.

The fields you need from `CONTRACT`:

- the schema/models block (table name → list of fields with `logicalType` (ODCS v3) or `type` (legacy ODCS v2), `required`, `unique`, `description`, `classification`, `enum`)
- `servers` (so the output port's server config is consistent with the contract)
- `terms` and `quality` rules — useful context but not required to materialize the table

### Step 2.5 — Validate the contract against Unity Catalog conventions

Scan the contract for convention bugs and offer to fix them in one pass, with the patched contract published back to Entropy Data. Dispatched off `servers[].type == "databricks"`. Other server types are skipped silently — add a section when extending support.

**Unity Catalog** — for every property in every schema covered by a `type: databricks` server:

- **Mixed-case `name`.** Unity Catalog folds unquoted identifiers to lowercase; `datacontract-cli` quotes `name` verbatim, so a `name: CustomerId` produces a query against `"CustomerId"` which won't match the stored `customerid` column. Normalize `name` to lowercase snake_case.
- **Redundant `physicalName`.** When `physicalName` equals the lowercase form of `name`, drop it.

If nothing is flagged, continue silently to Step 3. Otherwise list every fix (one bullet per property × issue) and ask:

> Found N convention issue(s) for `databricks` on contract `<CONTRACT_ID>`:
>   - property `<old-name>`: rename `name` → `<new-name>`
>   - property `<new-name>`: drop redundant `physicalName: <value>`
>
> Apply, save to `src/output_ports/v<N>/<contract-file>.odcs.yaml`, and publish back to Entropy Data? [Y/n]

On `Y`: patch the local file with `yq -i`, keep `version` unchanged (convention fix, not a schema change), `entropy-data datacontracts put <CONTRACT_ID> --file <path>`, re-read `CONTRACT`, continue. Stop on non-2xx.

On `n`: warn that `datacontract test` will fail on the un-normalized properties and continue. Don't re-ask this run.

### Step 3 — Translate ODCS schema to Lakeflow Python

**Output column identifier rule (applies to this step and Step 4).** Use the contract property's `name` directly as the Spark column name and the SQL alias. Don't substitute `physicalName` — `datacontract test` queries by `name`. Per-warehouse case conventions are enforced by Step 2.5; this step trusts the post-validation `name`.

**Pipeline module choice.** Default to `from pyspark import pipelines as dp` (Lakeflow Spark Declarative Pipelines, DBR 17.x+). The bundle template does not set `channel:` explicitly, so the default `current` channel applies — which is what docs recommend for production. To detect a legacy DLT bundle, look at the imports in any existing `src/**/*.py` file: if `import dlt` is in use, match that convention (swap `dp.` for `dlt.` throughout and emit `@dlt.table` everywhere — legacy DLT has no `materialized_view` decorator). Otherwise default to pyspark. Tell the user which module was picked.

For each contract:

1. Decide a Lakeflow table name. Default: the contract's schema/models key. Confirm with the user if it differs from the output-port server's table name.
2. **Identify candidate input ports.** Run `entropy-data access list --consumer-dataproduct <DATA_PRODUCT_ID> -o json` to list the access agreements where this product is the consumer. Each entry's `provider.dataProductId` / `provider.outputPortId` is an input port this product can read. Keep only agreements with `info.active: true` (status `approved`); ignore `pending` / `rejected`. Only fall back to a broader `entropy-data search query` if the user explicitly asks. If `src/input_ports/<provider-output-port-id>.py` already exists for an agreement, treat it as authoritative and skip recreating it.
3. Generate `src/output_ports/v1/<table>.py` — a `@dp.materialized_view` definition (batch body — the default for contract-driven output ports that read from other UC tables) that lists the contract columns explicitly with `F.col(...).cast(<spark-type>).alias("<column>")`. Use `@dp.table` instead only when the planned body uses `spark.readStream.table(...)` — i.e. the upstream input port is a streaming table and the consumer wants incremental append semantics. **Leave the body's source as a TODO** with a comment listing the candidate input ports from the previous step; do not invent business logic. After writing, also ensure the new file is referenced in `resources/<DATA_PRODUCT_ID>.pipeline.yml` under `libraries:` (init seeds an entry for the primary output port; for additional output ports beyond the first, append a new `- file: { path: ../src/output_ports/v1/<table>.py }` entry — see Step 4.1.5 for the same maintenance rule). Prepend a module docstring so a reader of the file knows which contract governs the schema:

   ```python
   """Governed by <contract-file>.odcs.yaml (ODCS id: <CONTRACT_ID>)."""

   from pyspark import pipelines as dp
   from pyspark.sql import SparkSession, functions as F

   spark: SparkSession  # injected by the Lakeflow runtime — no explicit construction needed


   @dp.materialized_view(
       name="<table>",
       comment="<from contract description>",
       table_properties={
           "data_contract.id": "<CONTRACT_ID>",
           "data_contract.file": "src/output_ports/v<N>/<contract-file>.odcs.yaml",
       },
   )
   @dp.expect_or_fail("not_null_<col>", "<col> IS NOT NULL")   # one per required: true
   @dp.expect_or_drop("valid_<col>", "<col> IN ('A', 'B')")    # one per enum
   # No decorator for unique: true — Lakeflow has no per-row uniqueness predicate;
   # `datacontract test` enforces uniqueness at the contract-test step.
   def <table>():
       # TODO: select from one of the candidate input ports listed below.
       # Candidates (active access agreements):
       #   - spark.read.table("<provider_dp_id>__<provider_op_id>")
       return spark.range(0).select(
           F.col("id").cast("bigint").alias("<col>"),
           ...
       )
   ```

   The contract file sits in the same directory as the Python, so the docstring names the file without a path prefix.

4. Map ODCS types to Spark types:

| ODCS `logicalType` (or legacy `type`) | Spark / Databricks |
|---|---|
| `string` / `text` | `string` |
| `integer` | `int` |
| `long` | `bigint` |
| `decimal` / `numeric` | `decimal(38,9)` |
| `float` | `float` |
| `double` | `double` |
| `boolean` | `boolean` |
| `timestamp` | `timestamp` |
| `date` | `date` |
| `bytes` | `binary` |
| `array<...>` | `array<...>` |
| `struct<...>` | `struct<...>` |

5. Map ODCS quality rules to Lakeflow expectations:

| ODCS field | Decorator | Severity choice |
|---|---|---|
| `required: true` | `@dp.expect_or_fail("not_null_<col>", "<col> IS NOT NULL")` | Output ports fail the run (the contract test would have failed anyway); inputs use `@dp.expect_or_drop` instead so upstream nulls don't take down our pipeline |
| `unique: true` | _(no decorator)_ | Lakeflow has no per-row uniqueness predicate; `datacontract test` enforces it at the contract-test step. Do not synthesize a SQL expectation — `"<col> IS NOT NULL"` would be redundant with the required-true rule above |
| `enum: [...]` | `@dp.expect_or_drop("valid_<col>", "<col> IN (...)")` | Drop rows with unexpected values; the contract test catches the count |
| `minLength` / `maxLength` / `minimum` / `maximum` | `@dp.expect("...", "...")` | Logged; not all backends enforce |
| Custom `quality:` block with SQL | `@dp.expect("<rule-name>", "<sql>")` | One decorator per rule; the SQL must be evaluable in the row context |

6. Map ODCS `classification` to Unity Catalog tag application. Tags are not expressible in `@dp.materialized_view` / `@dp.table` decorators — Lakeflow doesn't accept arbitrary column tags at definition time. Emit a sibling file `resources/<DATA_PRODUCT_ID>.tags.yml` describing the tags, and add a post-pipeline task to the existing `<DATA_PRODUCT_ID>_scheduled` job that applies them via SQL:

   ```yaml
   tasks:
     - task_key: apply_uc_tags
       depends_on:
         - task_key: run_pipeline
       sql_task:
         warehouse_id: ${var.tagging_warehouse_id}
         file:
           path: ../tags/<table>.sql
   ```

   The `tags/<table>.sql` file contains one statement per classified column:

   ```sql
   ALTER TABLE ${catalog}.${schema}.<table> ALTER COLUMN <col> SET TAGS ('classification' = 'pii');
   ```

   If `${var.tagging_warehouse_id}` is not defined in `databricks.yml`, ask the user for a warehouse id and add the variable. Skip this whole step if no contract property has a `classification` field.

### Step 4 — Implement the pipeline bodies

Ask the user: "Want me to wire the output-port tables to the input ports, or leave the source as TODOs?" Default to wiring them. If the user declines, skip this step and continue with the next one.

For each output port table:

1. **Declare each candidate input port as a `@dp.view` — one file per agreement, plus a trust-snapshot of the upstream contract.** For every agreement from Step 3.2:

   1. Fetch the provider data product (`entropy-data dataproducts get <provider-data-product-id> -o yaml`) to resolve the output port's `server` (`catalog.schema.table`) and linked contract id.
   2. Fetch the contract (`entropy-data datacontracts get <provider-contract-id> -o yaml`) for columns.
   3. Write the fetched contract to `src/input_ports/<provider-output-port-id>.odcs.yaml`. This is a **cached snapshot of what we trust upstream to produce** — it lets `git log` show when upstream's schema or quality rules changed under us. Do not hand-edit this file; the next run of this skill will refresh it from the platform. If the file already exists and the upstream contract has changed, surface the diff (so the user sees the drift) and ask before overwriting.
   4. Write the `@dp.view` wrapper to `src/input_ports/<provider-output-port-id>.py`:

      ```python
      """Cached upstream contract: <provider-output-port-id>.odcs.yaml (ODCS id: <provider-contract-id>).

      Source: <provider-data-product-id> / <provider-output-port-id>.
      Refreshed by `dataproduct-implement`; do not hand-edit.
      """

      from pyspark import pipelines as dp


      @dp.view(
          name="<provider_data_product_id>__<provider_output_port_id>",
          comment="<from upstream contract description>",
      )
      def <provider_data_product_id>__<provider_output_port_id>():
          return spark.read.table("<provider-catalog>.<provider-schema>.<provider-table>")
      ```

   The view name combines `<provider_dp_id>__<provider_op_id>` (double underscore) so it stays unique across agreements (two agreements with the same provider data product but different output ports do not collide). One pair of files (`*.odcs.yaml` + `*.py`) per agreement. Do not merge multiple agreements into a single file — each access grant should be independently visible in `git log` and easy to remove when revoked. If either file already exists for the same `<provider-output-port-id>`, surface the diff and ask before overwriting.

   5. **Append the new `.py` to the pipeline's libraries list.** Lakeflow rejects non-`.py`/`.sql` files in `libraries`, and `libraries.glob.include` cannot filter by extension, so each Python module must be listed explicitly in `resources/<DATA_PRODUCT_ID>.pipeline.yml`. Add an entry under `libraries:`:

      ```yaml
      libraries:
        - file:
            path: ../src/output_ports/v1/<table>.py        # seeded by dataproduct-init
        - file:
            path: ../src/input_ports/<provider-output-port-id>.py  # added by this step
      ```

      Idempotent: if an entry for the same path already exists, do not duplicate it.

2. **Match input columns to output columns**, in this order. Stop at the first signal that yields exactly one candidate.
   1. **Same semantic concept** — both columns declare a `type: semantics` entry in `authoritativeDefinitions` whose URL ends in the same path segment after normalization (lowercase, strip non-alphanumeric — so `…/processedTimestamp` matches `…/processed_timestamp`). Scheme, host, and org-id prefix differences don't disqualify.
   2. **Same name** (case-insensitive).
   3. **Token superset** — tokenize both names on `_` and case boundaries; the shorter side's tokens are all contained in the longer side's. Covers patterns like `<X>_NAME` ⊃ `<x>`, `<DOMAIN>_<X>` ⊃ `<x>`, `<X>_TIMESTAMP` ⊃ `timestamp`. Generic single-token output names (`id`, `name`, `type`, `value`, `code`, `key`) need a second signal — require (1) or a description echo (the upstream column's description names the output concept) before treating as a hit.

   If exactly one upstream column matches, project `F.col("<input_col>").cast("<spark_type>").alias("<output_name>")`. If multiple match, write `F.lit(None).cast("<type>").alias("<output_name>"),  # TODO: candidates: <names>`. If none match, write `F.lit(None).cast("<type>").alias("<output_name>"),  # TODO: source <description>`.

3. **Write the table body.**
   - **Single input source, columns match 1:1** → replace the TODO with `spark.read.table("<provider_dp_id>__<provider_op_id>")` (or `spark.readStream.table(...)` if the upstream is a streaming table and the consumer wants incremental semantics — in that case also switch the decorator to `@dp.table`). Project each output column with `F.col("<input_col>").cast("<spark_type>").alias("<output_col>")`.
   - **Multiple input sources** → leave the join logic as an inline TODO listing each candidate `spark.read.table(...)` reference and the join keys the user will need to confirm. Do not invent join predicates.
   - **Derived / aggregated columns** (sums, ratios, windows implied by the contract description but not present in any input) → leave as `F.lit(None).cast("<type>").alias("<col>"),  # TODO: compute <description from contract>`.

4. **Validate the bundle.** Run `databricks bundle validate --target dev` (cheap, no workspace roundtrip — equivalent to `dbt parse`) to catch Python syntax errors, broken `spark.read.table` references, and resource-graph cycles. If it fails, fix the generated code before continuing. Do not run `databricks bundle run` — that touches the workspace and is the user's call (use `dataproduct-deploy`).

### Step 5 — Stamp the data product as builder-managed

**If the data product was not on the platform in Step 1** (contract-first path, or both lookups 404'd), skip this step. The ODPS file that `entropy-data-publish` writes from the template already includes the `dataProductBuilder` customProperty, so the first CI publish creates the platform record with the stamp intact. There is nothing to patch.

Otherwise, check `DATA_PRODUCT.customProperties` for an entry with `property: "dataProductBuilder"` and `value: "https://github.com/entropy-data/dataproduct-builder-databricks"`. If it is already there, skip this step.

If missing, update the data product on Entropy Data so the platform records that it is managed by this builder. Do **not** rebuild the ODPS from a template — preserve every other field as fetched in Step 1.

1. Save the fetched data product to a temp file as YAML: `entropy-data dataproducts get <DATA_PRODUCT_ID> -o yaml > /tmp/<DATA_PRODUCT_ID>.odps.yaml`.
2. Append to the top-level `customProperties` list (create the list if absent):
   ```yaml
   customProperties:
     - property: "dataProductBuilder"
       value: "https://github.com/entropy-data/dataproduct-builder-databricks"
   ```
3. Push the patched file back: `entropy-data dataproducts put <DATA_PRODUCT_ID> --file /tmp/<DATA_PRODUCT_ID>.odps.yaml`.
4. Delete the temp file.

Forks of this plugin should substitute their own builder URL.

### Step 6 — Hand off to entropy-data-publish

Call the **entropy-data-publish** skill (in this same plugin) so any missing publishing artifacts get created (`<id>.odps.yaml`, `.github/workflows/data-product.yml`). Pass the parameters you already resolved in Step 1 so the user is not re-asked.

If `<id>.odps.yaml` already exists locally and disagrees with the fetched data product, **do not overwrite** — surface the diff and ask.

### Step 7 — Final report

End with this two-part recap. Use the shared `Status` enum (AGENTS.md § Final-report Status enum).

**Part 1 — outcome table.** One row per output port implemented.

| Artifact | Status | Details |
|---|---|---|
| Data product | … | `<DATA_PRODUCT_ID>` — `already present` (resolved on platform) / `deferred` (contract-first path; created by first CI publish) |
| `dataProductBuilder` customProperty | … | "added — pushed to Entropy Data" / "already present" / "seeded by template — first publish creates it" |
| Output-port data contract `<CONTRACT_ID>` | … | written to `src/output_ports/v<N>/<contract_id>.odcs.yaml` |
| Contract validation (UC convention) | … | "passed" / "normalized & republished: `<property>` × N" / "issues found, user declined fix" / "skipped (no rules for `<server-type>`)" |
| Input-port data contracts | … | `src/input_ports/<provider-output-port-id>.odcs.yaml` — `<N>` files written / refreshed (trust snapshots, one per active access agreement) / skipped |
| Input port `@dp.view` wrappers | … | `src/input_ports/<provider-output-port-id>.py` — `<N>` files written (one per active access agreement) / skipped |
| Output-port table for `<table>` | … | `src/output_ports/v1/<table>.py` — decorator (`@dp.materialized_view` / `@dp.table`), "wired to `<view>`" / "join TODO" / "skipped per user" |
| Quality expectations | … | `<N>` expectations generated from contract (required/enum/custom; uniqueness is enforced by `datacontract test`, not as a decorator) |
| Unity Catalog tag SQL | … | `tags/<table>.sql` — `<N>` columns tagged, post-pipeline task added to the scheduled job / "skipped (no classified columns)" |
| `databricks bundle validate` | … | "passed" / "failed: <reason>" / "skipped" |
| `entropy-data-publish` handoff | … | "ran" / "skipped" — see publish's own report for ODPS/workflow rows |

**Part 2 — next steps.** Bullet list, include only what applies:

- For each table with a join or derived-column TODO, list the inputs and the missing logic — one bullet per `<table>.py`.
- Run `dataproduct-deploy` locally to verify the generated bundle deploys and the pipeline runs.
- Run the contract test on the output ports against your workspace: `uv run datacontract test src/output_ports/v<N>/<file>.odcs.yaml --server production` for each contract. (`--server production` is the canonical server name shipped by the init template; pass `--server <name>` only if the contract uses a different one.)
- If the tag SQL was generated, confirm `var.tagging_warehouse_id` in `databricks.yml` points at a warehouse the job's run-as identity can use.
- Any deferred items from the publish skill's report.

If there is nothing in Part 2, write a single line: `No further action required.`

## Constraints

- **Contract is source of truth for schema, not logic.** Generate column names, types, and expectations from the contract. When wiring table bodies in Step 4, project and cast only — do not invent join predicates, aggregations, or column derivations. Anything not directly mappable from an input column stays a TODO.
- **Don't overwrite existing Python files**. If `src/output_ports/v1/<table>.py` already exists, surface the diff and ask before changing.
- **Don't run `databricks bundle deploy` or `databricks bundle run`** — that's `dataproduct-deploy`'s job, and it touches the workspace.
- **Idempotent**: re-running the skill with the same data product id should be a no-op when contract and local files already agree.
- **Do not commit or push** — leave VCS state to the user.
