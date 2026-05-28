---
name: dataproduct-deploy
description: Validate, deploy, and run the Declarative Automation Bundle's Lakeflow pipeline against a chosen Databricks target. Wraps `databricks bundle validate`, `databricks bundle deploy`, and `databricks bundle run`, then polls `databricks pipelines get` for completion and surfaces any failed expectations or pipeline-level errors. Trigger when the user asks to "deploy the data product", "run the Lakeflow pipeline", "deploy and run the bundle", or "ship this to dev".
---

# Deploy and run the Lakeflow pipeline

Take the local Declarative Automation Bundle and (1) validate it, (2) deploy it to the chosen target workspace, (3) trigger the Lakeflow Spark Declarative Pipeline, and (4) wait for the run to finish and report its status. This skill is the bridge between editing code locally and seeing tables materialize in Unity Catalog.

## When to use this vs. other skills

- **You just generated `@dp.table` files with `dataproduct-implement` and want to see them materialize** → this skill.
- **You changed a contract and want to re-test it against the live warehouse without redeploying** → `datacontract-test` is enough; no need to redeploy.
- **You want to schedule recurring runs** → the Lakeflow Job in `resources/<id>.job.yml` already does that; this skill triggers an ad-hoc run.

## How to run this skill

### Plan announcement (before Step 0)

Before running Step 0, print this plan to the user verbatim:

> Running **dataproduct-deploy**. I'll:
> 1. Pre-checks: confirm this is a bundle and the `databricks` CLI is authenticated.
> 2. Pick the target (`dev` unless you said otherwise) and the pipeline resource to run.
> 3. `databricks bundle validate` — fail fast if the bundle is broken.
> 4. `databricks bundle deploy --target <target>` — upload sources and create/update workspace resources.
> 5. `databricks bundle run <pipeline> --target <target>` — trigger an update of the Lakeflow pipeline.
> 6. Poll `databricks pipelines get` until the update completes, then surface row counts, failed expectations, and any pipeline-level error.
> 7. Report.
> 8. **Prod target only:** ask whether to trigger the Databricks integration ingest in Entropy Data and bind the materialized table to the data product as an asset.

Then proceed.

### Step 0 — Pre-checks

- Confirm `databricks.yml` exists at the working directory root. If not, stop and tell the user this skill must be run from a bundle root.
- Confirm `databricks --version` is on PATH. If not, surface the install line.
- Confirm `databricks auth describe` succeeds. If not, stop and tell the user to run `databricks auth login --host <workspace-url>`.

### Step 1 — Pick the target and pipeline

- **Target.** Default to `dev` (the `default: true` target in the init template; if a bundle still uses the legacy `default` target name, fall back to that). If the user named another target, use it. If the user did not specify and `databricks.yml` declares multiple targets, list them with their `mode:` and ask which one to use. **Never default to a target with `mode: production` without explicit user confirmation** — production deploys must be a deliberate choice.
- **Pipeline resource.** Read `resources/*.pipeline.yml`. If exactly one pipeline is declared, use it. If multiple, list them and ask which one. Remember the resource key as `PIPELINE_KEY` (e.g. `dp_acme_customer_activity`).

### Step 2 — Validate

```
databricks bundle validate --target <target>
```

If validation fails, surface the full CLI output and stop. Do **not** attempt to deploy a bundle that did not validate. Most validation failures are local (bad YAML, missing reference, undeclared variable) and fixable in the editor before re-running.

### Step 3 — Deploy

```
databricks bundle deploy --target <target>
```

This uploads `src/` and `resources/*` to the workspace, creates or updates the pipeline and job, and registers the bundle deployment under `${workspace.root_path}`. The deploy is **incremental**; only changed files transfer.

If the deploy fails on a permissions error (e.g. cannot write to `${workspace.root_path}`), surface the error and ask the user whether to (a) adjust `workspace.root_path` in `databricks.yml`, or (b) check their workspace permissions. Do not retry with different paths automatically.

If the user is deploying to a `mode: production` target for the first time, the CLI will ask for confirmation; pass through the prompt as-is — do not auto-answer.

### Step 4 — Run the pipeline

```
databricks bundle run <PIPELINE_KEY> --target <target>
```

This triggers an update on the Lakeflow pipeline. The CLI prints the update id and (depending on version) may stream events. Capture the `update_id` from stdout.

Optional flags the user may ask for:

- `--full-refresh-all` — wipes ALL of the pipeline's managed tables and re-runs the whole graph from scratch. Useful when schema-evolving the contract; destructive (drops every row in every pipeline table). Confirm with the user before passing this flag.
- `--full-refresh <table1,table2>` — same wipe-and-recompute semantics but limited to the comma-separated table list. Use when only a subset of the contract changed shape.
- `--refresh-all` / `--refresh <tables>` — recompute without dropping rows first. Non-destructive alternative to `--full-refresh-all` / `--full-refresh`.
- `--restart` — cancels any in-flight update before starting a new one.

If the CLI does not stream events on this version, fall through to Step 5 to poll.

### Step 5 — Poll for completion

If `bundle run` returned before the update finished:

1. Resolve the pipeline id: `databricks bundle summary --target <target> -o json | jq '.resources.pipelines["<PIPELINE_KEY>"].id'`.
2. Poll with `databricks pipelines get <pipeline-id> -o json` every 15 seconds. Stop when `state.life_cycle_state` is one of `COMPLETED`, `FAILED`, `CANCELED`, or `IDLE` (with the latest_update id matching).
3. While polling, surface a one-line status update each iteration: `[run <update_id>] state=<lifecycle> latest=<update_state> elapsed=<MM:SS>`.
4. Cap the wait at 30 minutes by default; if exceeded, stop polling and tell the user the run is still in progress with the update id so they can check in the Databricks UI.

Once the update finishes, fetch the update detail:

```
databricks pipelines get-update <pipeline-id> <update-id> -o json
```

Extract:

- `state` (`COMPLETED` / `FAILED` / `CANCELED`)
- `cause` and `cluster_id` (for the link the user can open in the Databricks UI)
- per-flow row counts and expectation results from `state.events` if present

### Step 6 — Report

End with this two-part recap. Use the shared `Status` enum (AGENTS.md § Final-report Status enum). For this skill the relevant statuses are `passed`, `failed`, and `deferred` (run still in progress at the timeout).

**Part 1 — outcome table.**

| Artifact | Status | Details |
|---|---|---|
| `databricks bundle validate` | … | "passed" / "failed: <one-line reason>" |
| `databricks bundle deploy --target <target>` | … | "deployed to `<workspace>/<root_path>`" / "failed: <one-line reason>" |
| Pipeline update | … | update id, lifecycle state, elapsed time |
| Materialized tables | … | per-flow rows written (from update events) — `<table>: <N> rows` |
| Failed expectations | … | per-rule failure count if any — `<table>.<rule>: <N> dropped/failed` |
| Pipeline events (errors) | … | first 3 error events with timestamp and message, if any |

**Part 2 — next steps.** Bullet list, include only what applies:

- For each failed expectation, the field/rule and the corresponding ODCS line — point at `datacontract-edit` if the rule itself is wrong, or at the contract test if the data is the problem.
- If the pipeline failed mid-flow, surface the link to the run in the Databricks UI: `https://<workspace>/#joblist/pipelines/<pipeline-id>/updates/<update-id>`.
- If the run succeeded, suggest running `uv run datacontract test src/output_ports/v<N>/<contract>.odcs.yaml --server production` to confirm the published data conforms end-to-end.
- If `--full-refresh-all` or `--full-refresh <tables>` was used, remind the user that downstream consumers may have seen empty tables briefly during the refresh window.

If the run completed without errors or failed expectations, write a single line: `Pipeline <PIPELINE_KEY> ran successfully on <target>. <N> tables materialized.`

### Step 7 — Assign UC table to the data product as an asset (prod only)

Run this step only when the deploy target was `prod` (or any target with `mode: production`) **and** the pipeline run succeeded. Skip entirely for dev — dev tables aren't customer-facing and shouldn't appear as Entropy Data assets.

Entropy Data discovers UC tables via the Databricks integration, which runs nightly. To make the freshly materialized table appear immediately in the platform's catalog (and bind it to this data product), the skill can trigger the ingest on demand and then assign.

**Ask the user — required confirmation gate:**

> The prod pipeline materialized `<catalog>.<schema>.<table>`. Trigger the Databricks integration ingest now to register the new tables as Entropy Data assets, then bind them to the data product? (yes / no / ingest only)

If **no**, skip the step and mark as `skipped` in the report.

If **ingest only**: do part (a) below, skip part (b).

If **yes**: do both (a) and (b).

(a) **Trigger ingest.** Resolve the Databricks integration id:

```
uv run entropy-data integrations list -o json | jq -r '.[] | select(.source == "databricks") | .id'
```

If exactly one row is returned, use it. If multiple, ask the user which workspace integration to run. Then:

```
uv run entropy-data integrations run <integration-id> --wait --timeout 600
```

`--wait` polls until the ingest reaches a terminal state. On `SUCCESS`, proceed to (b). On `FAILED` / `CANCELLED`, surface the error and stop — do not retry without explicit user input.

(b) **Bind the asset to the data product.** Resolve the data product id from `<id>.odps.yaml`. Find the asset matching the materialized table:

```
uv run entropy-data assets list -o json | jq '.[] | select(.info.qualifiedName == "<catalog>.<schema>.<table>")'
```

If exactly one asset matches, capture its `id` as `ASSET_ID`. If multiple match (rare — happens when older deletions leak), surface them and ask the user. If zero match, the ingest didn't pick the table up yet — wait 30 seconds and retry once before giving up.

The exact binding payload format depends on the platform schema and is best discovered at runtime — start by reading `uv run entropy-data assets get <ASSET_ID> -o json` for the current shape, then check whether the DP body or the asset body holds the link by inspecting one already-assigned asset (`uv run entropy-data assets list -o json | jq '.[] | select(.relationships // [] | length > 0)'`). Construct the binding body accordingly and apply with `uv run entropy-data assets put <ASSET_ID> --file -` (stdin). Surface the exact request body to the user before applying. If the body shape is unclear, ask the user — do not guess against the platform.

Mark per-table in the report:

- `created` — ingest ran and asset bound for the first time.
- `updated` — asset was already known; binding added/refreshed.
- `already present` — asset and binding both already wired.
- `skipped` — user declined the gate.
- `failed` — ingest or bind raised a CLI error (include the error verbatim).

### Add to Step 6 — Report

When Step 7 ran (target=prod, successful run), append these rows to the Part 1 outcome table:

| Asset assignment | … | per-table `<catalog>.<schema>.<table>: <status>` |
| Databricks integration ingest | … | "ran (<elapsed>s, <N> assets updated)" / "skipped" / "failed: <error>" |

## Constraints

- **No silent production deploys.** A `mode: production` target always requires explicit user confirmation, even when the user asked to deploy. The CLI's built-in confirmation handles this; do not bypass it.
- **No `--full-refresh-all` or `--full-refresh <tables>` without confirmation.** Both drop rows in the pipeline's managed tables (the former across the whole graph, the latter for the named tables only). Ask before passing either flag.
- **No retries on permissions errors.** A failed deploy due to permissions or missing principals needs human intervention; retrying does not help and confuses the audit trail.
- **No edits to bundle or pipeline code.** This skill runs the bundle as-is. If a validation error names a fixable issue in `databricks.yml` or `src/`, surface it but do not auto-edit — that's the user's call.
- **Idempotent**: running the skill twice in succession when nothing changed redeploys (no-op upload) and runs a fresh update. The pipeline state in UC may change if upstream data changed; that is expected.
