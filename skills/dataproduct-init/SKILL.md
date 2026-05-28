---
name: dataproduct-init
description: Initialize a brand-new Databricks data product from scratch — create databricks.yml (Declarative Automation Bundle with `dev` and `prod` targets), a serverless Lakeflow Spark Declarative Pipeline resource, a Lakeflow Job that schedules it, the src/{input_ports,transformations,output_ports/v1}/ layout, pyproject.toml, README, and .gitignore. After scaffolding, hands off to the entropy-data-publish skill to add the publishing layer (ODPS, ODCS, GitHub Actions). Trigger when the user asks to start a new data product, scaffold a new Databricks bundle, or "create a data product from scratch."
---

# Initialize a new Databricks data product

Create a new Databricks data product project that follows the Entropy Data conventions. This skill handles the **greenfield** case — empty directory, no bundle yet. For an existing bundle that just needs the Entropy Data layer, use the **entropy-data-publish** skill instead.

## What this skill produces

After running, the directory contains:

```
.
├── databricks.yml
├── .gitignore
├── README.md
├── pyproject.toml
├── resources/
│   ├── <data-product-id>.pipeline.yml
│   └── <data-product-id>.job.yml
└── src/
    ├── input_ports/.gitkeep
    ├── transformations/.gitkeep
    └── output_ports/v1/.gitkeep
```

It then invokes **entropy-data-publish** to add `<id>.odps.yaml`, the output-port contract under `src/output_ports/v1/<contract>.odcs.yaml`, and `.github/workflows/data-product.yml`.

## How to run this skill

> `${PLUGIN_ROOT}` below refers to the root of this plugin — the directory that contains `skills/`. On Claude Code it is set automatically as `${CLAUDE_PLUGIN_ROOT}` — use that. On any other agent (Codex, Copilot CLI, etc.) it is unset; resolve it as `../..` relative to **this `SKILL.md` file's directory** (i.e. the grandparent of `skills/<this-skill>/`).

### Plan announcement (before Step 1)

Before running Step 1, print this plan to the user verbatim:

> Running **dataproduct-init**. I'll:
> 1. Pre-checks: confirm the working directory is empty, the `databricks` and `entropy-data` CLIs are installed and authenticated, then ask whether this is a brand-new data product or one that already has an ODPS draft in Entropy Data.
> 2. Gather parameters. If you point me at an existing draft, I pull them from the fetched ODPS; otherwise I'll ask you in one batched question (data product id, name, team, catalog, schema, table).
> 3. Check that the workspace's Databricks Runtime supports `pyspark.pipelines` (the current Lakeflow Python module). If only older runtimes are available, ask whether to fall back to legacy `dlt`.
> 4. Scaffold the bundle (`databricks.yml`, `resources/*.yml`, `src/` layout, `pyproject.toml`, `README.md`, `.gitignore`).
> 5. Hand off to `entropy-data-publish` for the publishing layer (ODPS, ODCS, GitHub Actions).
> 6. Summarize what was scaffolded and the next manual steps.

Then proceed.

### Step 1 — Pre-checks

- Confirm the working directory is empty, or that it contains only files the user is fine with (e.g. an empty git repo, a `LICENSE`, or a `README.md` that will be overwritten).
- If `databricks.yml` already exists, **stop** and tell the user to use the `entropy-data-publish` skill instead. This skill is for greenfield only.
- **Databricks CLI**: `databricks --version` must be on PATH. If not, install via `brew install databricks/tap/databricks` (macOS) or follow https://docs.databricks.com/aws/en/dev-tools/cli/install — surface the install instruction and stop.
- **Databricks auth**: `databricks auth describe` must succeed. If not, tell the user to authenticate via one of: `databricks auth login --host <workspace-url>` (OAuth U2M — recommended for local dev), `DATABRICKS_HOST` + `DATABRICKS_CLIENT_ID` + `DATABRICKS_CLIENT_SECRET` env vars (OAuth M2M with a service principal — recommended for CI), or `DATABRICKS_HOST` + `DATABRICKS_TOKEN` (legacy PAT).
- **Check whether the data product already exists in Entropy Data.** Ask the user: "Is there already an ODPS draft, a published data contract, or is this entirely new? If something exists, paste the data product id, the contract id, or the URL." Four outcomes:
  - **New** — continue to Step 2 with no `DATA_PRODUCT` or `CONTRACT` preloaded.
  - **Existing data product id/URL given** — extract the trailing id from a URL, then run `entropy-data dataproducts get <id> -o yaml`. If the lookup succeeds, remember the response as `DATA_PRODUCT` and use it in Step 2a.
  - **Existing data contract id/URL given (no draft data product yet)** — common when the user spec'd the schema first in the contract editor. Run `entropy-data datacontracts get <id> -o yaml`. If the lookup succeeds, remember the response as `CONTRACT`, treat the product as new (it will be created by the first publish), and use Step 2b to derive parameters from the contract.
  - **Unknown id type** — if the user is not sure whether they have a contract or a data product, try both lookups in order (`dataproducts get` then, on 404, `datacontracts get`). The first one that succeeds determines the path. If both 404, tell the user and ask whether to (a) try a different id, (b) proceed as new with that id, or (c) abort.
- **Entropy Data CLI prerequisites for the lookup** (init is the one skill where this is global, not via the project venv — see AGENTS.md § Install pattern. The directory has no `pyproject.toml` yet, so `uv run entropy-data` is unavailable until Step 4 scaffolds the project and the user runs `uv sync`. Subsequent skills use `uv run entropy-data` exclusively.): `entropy-data --version` must be on PATH (install once with `uv tool install entropy-data` if missing) and `entropy-data connection test` must succeed. If either fails, surface the error and ask the user whether to (a) fix the CLI and retry, or (b) skip the lookup and proceed as if new. Don't prompt for the API key yourself.

### Step 2 — Gather parameters

#### Step 2a — If `DATA_PRODUCT` was loaded from Entropy Data

Derive parameters from the fetched ODPS. Treat the draft as authoritative; only ask the user for fields it does not specify.

| Parameter | Source from `DATA_PRODUCT` |
|---|---|
| `DATA_PRODUCT_ID` | `id` |
| `DATA_PRODUCT_NAME` | `name` |
| `PURPOSE` | `description.purpose` (fall back to ask) |
| `TEAM_NAME` | `team.name` or `team.id` (fall back to ask, see picking note below) |
| `CATALOG` | output port's `server.catalog` (fall back to ask) |
| `SCHEMA` | output port's `server.schema` (fall back to ask) |
| `TABLE` | output port's `server.table`, or the linked contract's top-level schema key (fall back to ask) |

If the draft declares more than one output port, ask the user which one to use for `CATALOG`/`SCHEMA`/`TABLE`. Default to the first.

If the draft's first output port's `server.type` is not `databricks`, stop and tell the user this plugin only handles Databricks; for other platforms, use the matching builder (e.g. `dataproduct-builder-dbt` for non-Databricks dbt projects).

Show the user the derived parameters and ask for confirmation before continuing. Collect any missing fields in one batched question.

#### Step 2b — If `CONTRACT` was loaded from Entropy Data (no draft data product)

Derive parameters from the fetched contract:

| Parameter | Source from `CONTRACT` |
|---|---|
| `DATA_PRODUCT_ID` | Derived from `CONTRACT.id` — see AGENTS.md § Deriving `DATA_PRODUCT_ID` from a contract id. Confirm with the user before continuing |
| `DATA_PRODUCT_NAME` | `CONTRACT.name` |
| `PURPOSE` | `CONTRACT.description.purpose` (fall back to ask) |
| `TEAM_NAME` | `CONTRACT.team.name` or `team.id` (fall back to ask; see picking note in Step 2c) |
| `CATALOG` | First `servers[]` block with `type: databricks`: its `catalog` (fall back to ask) |
| `SCHEMA` | Same server block's `schema` (fall back to ask) |
| `TABLE` | `CONTRACT.schema[0].name` (the top-level schema key; fall back to ask if absent) |

If the contract has no `servers[]` entry of `type: databricks`, stop and tell the user this plugin only handles Databricks contracts.

Show the derived parameters and ask for confirmation. Collect any missing fields in one batched question. In Step 5 the `CONTRACT` will be written to `src/output_ports/v1/<CONTRACT.id>.odcs.yaml` so entropy-data-publish's audit sees it as already present.

#### Step 2c — If neither was loaded (new product)

Ask the user for these in a single prompt. Do not generate any files until you have all of them.

| Parameter | Description | Example |
|---|---|---|
| `DATA_PRODUCT_ID` | Stable id, snake_case, also the bundle name | `dp_acme_customer_activity` |
| `DATA_PRODUCT_NAME` | Human-friendly name | `Customer Activity` |
| `PURPOSE` | One sentence — why this data product exists | `Customer activity for customer success.` |
| `TEAM_NAME` | Owning team | `customer-success` (see note below) |
| `CATALOG` | Unity Catalog catalog | `entropy_data_prod` |
| `SCHEMA` | Unity Catalog schema | `dp_acme_customer_activity` |
| `TABLE` | First output port table name | `customer_activity` |

**Picking `TEAM_NAME`**: prefer a team `id` that already exists in Entropy Data so the data product slots into the team-scoped views in the UI. If the user does not already know the team id, invoke the **entropy-data-teams** skill (in this same plugin), let them pick, and use the returned `id` as `TEAM_NAME`. A free-text value is still accepted, but the registered id is preferred.

**Unity Catalog naming**: catalog/schema/table identifiers should be lowercase snake_case. Unity Catalog folds unquoted identifiers to lowercase, so a mixed-case `CustomerActivity` becomes `customeractivity` and breaks downstream contract tests that look for the original casing. The validator in `dataproduct-implement` Step 2.5 enforces this on the ODCS side; doing it right at init time avoids the rewrite.

### Step 3 — Pick the Lakeflow Python module

The current Lakeflow Spark Declarative Pipelines API uses `from pyspark import pipelines as dp`. It runs on Databricks Runtime 17.x+ on the default `current` channel (the docs explicitly recommend `current` for production workloads — the bundle template does not set `channel:` explicitly so the default applies). Older runtimes only ship the legacy `import dlt` module.

Decide which to use:

1. Run `databricks clusters spark-versions -o json` and look for any entry with `key` starting with `17.` (or higher). If at least one exists, **default to `pyspark.pipelines`** with no explicit `channel:` (i.e. default `current`).
2. If only older runtimes are listed, warn the user that the workspace doesn't surface DBR 17.x; ask whether to (a) proceed with `pyspark.pipelines` anyway (will fail at runtime if the cluster pool is constrained) or (b) fall back to `import dlt`. Default to (a) — most workspaces allow new runtimes even if older ones are pinned for compatibility.

Remember the choice as `PIPELINE_MODULE` (`pyspark` or `dlt`). The template defaults to `pyspark`; if `dlt`, swap the import line and decorator references during file write.

Note: `channel: preview` exists for testing upcoming runtime versions and should only be set on a deliberate staging pipeline, not the main one. The plugin does not set `channel:` by default.

### Step 4 — Scaffold the bundle

Templates are at `${PLUGIN_ROOT}/skills/dataproduct-init/templates/`. Copy each template into the working directory, substituting placeholders. Two of the resource files (`<id>.pipeline.yml`, `<id>.job.yml`) are named after `DATA_PRODUCT_ID` — the templates ship with literal `pipeline.yml` / `job.yml` names; rename them on write.

| Template | Destination |
|---|---|
| `databricks.yml` | `databricks.yml` |
| `.gitignore` | `.gitignore` (merge if one already exists; do not overwrite) |
| `README.md` | `README.md` (merge or back up if one already exists) |
| `pyproject.toml` | `pyproject.toml` |
| `resources/pipeline.yml` | `resources/<DATA_PRODUCT_ID>.pipeline.yml` |
| `resources/job.yml` | `resources/<DATA_PRODUCT_ID>.job.yml` |
| `src/input_ports/.gitkeep` | `src/input_ports/.gitkeep` |
| `src/transformations/.gitkeep` | `src/transformations/.gitkeep` |
| `src/output_ports/v1/.gitkeep` | `src/output_ports/v1/.gitkeep` |

After writing, run `databricks bundle validate --target dev` from the working directory to verify the bundle parses. (Do **not** validate against `prod` at init time — the `prod` target ships with placeholder values for `run_as.service_principal_name` and is expected to fail validation until the user fills them in before their first prod deploy.) If `dev` validation fails, surface the error and ask whether to (a) fix it now or (b) continue to Step 5 and address it after the ODPS/ODCS files exist (some validation errors come from missing schemas the publish skill creates).

### Step 5 — Hand off to entropy-data-publish

Now the bundle skeleton is in place. Invoke the **entropy-data-publish** skill (in this same plugin) to add ODPS, ODCS, and the GitHub Actions workflow.

Pass the parameters you already collected (`DATA_PRODUCT_ID`, `DATA_PRODUCT_NAME`, `PURPOSE`, `TEAM_NAME`, `CATALOG`, `SCHEMA`, `TABLE`) so the user does not have to answer them again. `entropy-data-publish` resolves `API_HOST` itself from the entropy-data CLI connection.

**If `DATA_PRODUCT` was loaded from Entropy Data in Step 1**, do this *before* invoking entropy-data-publish so its audit sees the artifacts as already present (no template-generated stubs that would clobber the draft):

1. Write the fetched ODPS to `<DATA_PRODUCT_ID>.odps.yaml` (the same YAML the CLI returned — do not regenerate from the template).
2. For each output port in the draft that references a contract id, fetch and save it: `entropy-data datacontracts get <contract-id> -o yaml > src/output_ports/v<N>/<contract-id>.odcs.yaml` (default `v1` if the output port does not declare a version).
3. If any of these fetches fail (404, network error), surface the error and continue — entropy-data-publish will create stubs from templates for whatever is missing.

**If `CONTRACT` was loaded from Entropy Data in Step 1** (the contract-first path), do this *before* invoking entropy-data-publish so its audit sees the output-port contract as already present:

1. Write the fetched contract to `src/output_ports/v1/<CONTRACT.id>.odcs.yaml` (the same YAML the CLI returned — preserve it verbatim).
2. Do **not** write an ODPS yet; entropy-data-publish will create it from the template using the `CONTRACT_ID` derived from the file. The new ODPS ships with the `dataProductBuilder` customProperty already in place.

The publish skill will run its own audit. For a brand-new product, every artifact is missing and created; for a draft-loaded product, ODPS and ODCS show as `already present`; for the contract-first path, ODCS shows as `already present` and ODPS is created from the template.

### Step 6 — Final report

After both skills have run, end with this two-part recap. Use the shared `Status` enum (AGENTS.md § Final-report Status enum).

**Part 1 — outcome table.** State the mode at the top of the recap — one of `Mode: new product`, `Mode: initialized from existing draft <DATA_PRODUCT_ID>`, or `Mode: initialized from existing data contract <CONTRACT.id>`.

| Artifact | Status | Details |
|---|---|---|
| `databricks.yml` | … | bundle name = `<DATA_PRODUCT_ID>`, `dev` (default) + `prod` targets, top-level `presets.tags: { data_product_id }` |
| `resources/<id>.pipeline.yml` | … | serverless Lakeflow pipeline, channel = default (`current`), module = `<PIPELINE_MODULE>` |
| `resources/<id>.job.yml` | … | scheduled Lakeflow Job (daily 06:00 UTC by default); pause status driven by target preset (paused in dev, unpaused in prod) |
| `pyproject.toml` | … | dev deps: datacontract-cli, entropy-data, pytest, ruff |
| `README.md` | … | new or merged into existing |
| `.gitignore` | … | new or merged into existing |
| `src/` layout | … | `input_ports/`, `transformations/`, `output_ports/v1/` with `.gitkeep` placeholders |
| `databricks bundle validate --target dev` | … | "passed" / "failed: <reason>" |
| `prod` target customization required | deferred | Two placeholders must be replaced before the first prod deploy: `run_as.service_principal_name: <fill-in-before-prod-deploy>` (CI service principal app id) and `variables.notifications_email.default: <set-before-prod-deploy>` (pipeline failure alert address). `workspace.root_path` defaults to `/Workspace/Shared/.bundle/<bundle>/prod` — change to an SP-scoped path if `/Workspace/Shared/` is not writable. |
| `<DATA_PRODUCT_ID>.odps.yaml` (from draft) | … | only when initialized from existing draft: `created` (fetched) or `skipped` (fetch failed) |
| Output-port ODCS files (from draft) | … | only when initialized from existing draft: `<N>` file(s) under `src/output_ports/v<N>/`, or `skipped` if no contracts were linked |
| `entropy-data-publish` handoff | … | "ran" / "skipped" — see publish's own report for ODPS/ODCS/workflow rows |

**Part 2 — next steps.** This is the canonical "scaffold → wired pipeline" loop (see AGENTS.md § Lifecycle). Print the literal commands the user can copy-paste, substituting concrete values. Include only the items that apply.

> The commands below use `gh` (GitHub CLI) and a `.github/workflows/` CI surface — the plugin's default shape. **Forks** for organizations on GitLab / Azure DevOps / Bitbucket replace `gh` with the equivalent CLI (`glab`, `az devops`, etc.) and swap `.github/workflows/data-product.yml` for the matching pipeline format. See the upstream README's "Customization" section.


```bash
# (1) Install Python dev deps locally.
uv sync

# (2) Create a Python stub for the output port (or run dataproduct-implement).
#     Skip if you'll run dataproduct-implement next — it does the same thing
#     from the data contract.

# (3) Initialize VCS and push to GitHub. Adjust the org / visibility / branch
#     to your conventions.
git init
git add .
git commit -m "scaffold <DATA_PRODUCT_ID>"
gh repo create <github-org>/<DATA_PRODUCT_ID> --private --source=. --push

# (4) Set CI variables (non-credentials) and secrets (real credentials).
#     HOST, CLIENT_ID, HTTP_PATH are identifiers / URLs / paths — not
#     credentials — so they go in variables, not secrets.
gh variable set DATABRICKS_HOST                   --body "<workspace-url>"
gh variable set DATABRICKS_CLIENT_ID              --body "<service-principal-app-id>"
gh variable set DATACONTRACT_DATABRICKS_HTTP_PATH --body "/sql/1.0/warehouses/<warehouse-id>"
gh secret   set DATABRICKS_CLIENT_SECRET          --body "<service-principal-oauth-secret>"
gh secret   set ENTROPY_DATA_API_KEY              --body "<entropy-data-api-key>"
gh secret   set DATACONTRACT_DATABRICKS_TOKEN     --body "<sp-or-personal-access-token>"
# Prefer legacy PAT auth? Swap CLIENT_ID/CLIENT_SECRET for DATABRICKS_TOKEN
# in .github/workflows/data-product.yml and as a single secret here.

# (5) Before the first prod deploy — open databricks.yml and replace these
#     two placeholders:
#       - `run_as.service_principal_name: <fill-in-before-prod-deploy>` →
#         the CI service principal's application id.
#       - `variables.notifications_email.default: <set-before-prod-deploy>` →
#         a real address (or distribution list) for pipeline failure alerts.
#         Required only for prod; dev deploys skip the email_notifications
#         block. Empty / placeholder values panic the Databricks Jobs API.
#     Also adjust `workspace.root_path` if /Workspace/Shared/ is not writable
#     for that SP.

# (6) Push to main → CI workflow runs → entropy-data dataproducts put +
#     entropy-data datacontracts put register the records on the platform
#     for the first time.

# (7) Re-run `entropy-data-publish` from this working directory to register
#     the git connections (it will detect the now-present platform records).

# (8) Request access agreements for any upstream input ports. Look up each
#     upstream's data product id + output port name first; --purpose is the
#     business justification you want logged on the agreement.
entropy-data access request <provider-dp-id> <provider-output-port-id> \
  --consumer-dataproduct <DATA_PRODUCT_ID> \
  --purpose "<one-sentence justification>"

# (9) Once agreements are approved, re-run `dataproduct-implement` to wire
#     the input ports into the output-port table body.
```

If there is nothing in Part 2 to print (greenfield with no scaffolding done), write a single line: `No further action required.`

## Constraints

- **Do not run `databricks bundle init`** — the upstream template (`lakeflow-pipelines`) generates an example layout that does not match the Entropy Data conventions. Use the templates here.
- **Do not commit secrets**. Tokens belong in env vars or repo secrets, never in `databricks.yml`.
- **Do not invent credentials**. The bundle template omits `workspace.host` entirely — the CLI rejects `${DATABRICKS_HOST}` interpolation for that field. The user supplies the workspace via the `DATABRICKS_HOST` env var, a `.databrickscfg` profile (`--profile <name>`), or by hardcoding the URL per target after init. Don't put a workspace URL in the template.
- **Idempotent on greenfield only**. If `databricks.yml` exists, route the user to `entropy-data-publish`; do not overwrite.
- **Do not run `git init`, `git commit`, or any push** — surface those as next steps for the user instead.
- **Use lowercase Unity Catalog identifiers**. UC folds unquoted identifiers to lowercase. Names entered uppercase get rewritten to lowercase before substitution, with a note in the final report.
