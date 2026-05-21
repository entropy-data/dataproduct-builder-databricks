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

> `${PLUGIN_ROOT}` below refers to the root of this plugin — the directory that contains `skills/`. On Claude Code it is set automatically as `${CLAUDE_PLUGIN_ROOT}` — use that. On any other agent (Codex, Copilot CLI, etc.) it is unset; resolve it as `../..` relative to **this `SKILL.md` file's directory** (i.e. the grandparent of `skills/<this-skill>/`).

### Plan announcement (before Step 0)

Before running Step 0, print this plan to the user verbatim:

> Running **dataproduct-deploy**. I'll:
> 1. Pre-checks: confirm this is a bundle and the `databricks` CLI is authenticated.
> 2. Pick the target (`default` unless you said otherwise) and the pipeline resource to run.
> 3. `databricks bundle validate` — fail fast if the bundle is broken.
> 4. `databricks bundle deploy --target <target>` — upload sources and create/update workspace resources.
> 5. `databricks bundle run <pipeline> --target <target>` — trigger an update of the Lakeflow pipeline.
> 6. Poll `databricks pipelines get` until the update completes, then surface row counts, failed expectations, and any pipeline-level error.
> 7. Report.

Then proceed.

### Step 0 — Pre-checks

- Confirm `databricks.yml` exists at the working directory root. If not, stop and tell the user this skill must be run from a bundle root.
- Confirm `databricks --version` is on PATH. If not, surface the install line.
- Confirm `databricks auth describe` succeeds. If not, stop and tell the user to run `databricks auth login --host <workspace-url>`.

### Step 1 — Pick the target and pipeline

- **Target.** Default to `default` (the single target in the init template). If the user named another target, use it. If the user did not specify and `databricks.yml` declares multiple targets, list them with their `mode:` and ask which one to use. **Never default to a target with `mode: production` without explicit user confirmation** — production deploys must be a deliberate choice.
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

- `--full-refresh` — wipes the target schema's pipeline-managed tables and re-runs from scratch. Useful when schema-evolving the contract; destructive (drops all current rows). Confirm with the user before passing this flag.
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

End with this two-part recap. Use the same `Status` enum the other skills use: `created`, `updated`, `already present`, `deferred`, `skipped`. For this skill, the relevant statuses are `passed`, `failed`, and `deferred` (run still in progress at the timeout).

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
- If the run succeeded, suggest running `datacontract test src/output_ports/v<N>/<contract>.odcs.yaml` to confirm the published data conforms end-to-end.
- If `--full-refresh` was used, remind the user that downstream consumers may have seen empty tables briefly during the refresh window.

If the run completed without errors or failed expectations, write a single line: `Pipeline <PIPELINE_KEY> ran successfully on <target>. <N> tables materialized.`

## Constraints

- **No silent production deploys.** A `mode: production` target always requires explicit user confirmation, even when the user asked to deploy. The CLI's built-in confirmation handles this; do not bypass it.
- **No `--full-refresh` without confirmation.** It drops all rows in the pipeline's target tables. Ask before passing it.
- **No retries on permissions errors.** A failed deploy due to permissions or missing principals needs human intervention; retrying does not help and confuses the audit trail.
- **No edits to bundle or pipeline code.** This skill runs the bundle as-is. If a validation error names a fixable issue in `databricks.yml` or `src/`, surface it but do not auto-edit — that's the user's call.
- **Idempotent**: running the skill twice in succession when nothing changed redeploys (no-op upload) and runs a fresh update. The pipeline state in UC may change if upstream data changed; that is expected.
