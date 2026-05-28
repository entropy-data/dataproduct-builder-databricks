---
name: entropy-data-publish
description: Audit a Declarative Automation Bundle against the Entropy Data reference layout and add anything missing — Open Data Product Specification (ODPS), Open Data Contract Standard (ODCS), and the GitHub Actions publish workflow that deploys the bundle, runs the Lakeflow pipeline, runs the contract test, and publishes ODPS/ODCS back to Entropy Data. Trigger when the user asks to integrate a Databricks bundle with Entropy Data, set up Entropy Data publishing, or check whether a bundle follows the Entropy Data conventions.
---

# Entropy Data integration for Databricks bundles

Make sure a Databricks Declarative Automation Bundle is well-integrated with Entropy Data.

## What "well-integrated" means

A bundle is well-integrated with Entropy Data when it has all of:

| # | Artifact | Path | Purpose |
|---|---|---|---|
| 1 | Open Data Product Specification | `<data-product-id>.odps.yaml` at repo root | Declares the data product, team, output ports |
| 2 | Output-port data contracts | `src/output_ports/v<N>/<contract-id>.odcs.yaml` (one per output port — what this data product **commits** to produce) | Schema + server config the contract test runs against; colocated with the `@dp.materialized_view` / `@dp.table` definition that implements it |
| 3 | Input-port data contracts | `src/input_ports/<provider-output-port-id>.odcs.yaml` (one per active access agreement — what this data product **trusts** upstream to produce) | Cached snapshot of the upstream provider's ODCS; refreshed via `entropy-data datacontracts get`, never hand-edited |
| 4 | Bundle layout | `src/{input_ports,transformations,output_ports/v1}/` | Convention that mirrors the data product's lifecycle |
| 5 | Publish workflow | `.github/workflows/data-product.yml` | CI: `databricks bundle deploy` → `bundle run` → `datacontract test` → publish ODPS + output ODCS |
| 6 | Git connections | One per ODPS + one per output-port ODCS, registered via `entropy-data dataproducts gitconnection put` and `entropy-data datacontracts gitconnection put` | Lets Entropy Data link the published spec back to the YAML in the repo, and enables `pull` / `push` / `push-pr` from the CLI. Input-port ODCS files are *not* registered — they belong to the upstream data product, which owns its own git connection |

## How to run this skill

Work in this exact order. Do not skip the audit.

> `${PLUGIN_ROOT}` below refers to the root of this plugin — the directory that contains `skills/`. On Claude Code it is set automatically as `${CLAUDE_PLUGIN_ROOT}` — use that. On any other agent (Codex, Copilot CLI, etc.) it is unset; resolve it as `../..` relative to **this `SKILL.md` file's directory** (i.e. the grandparent of `skills/<this-skill>/`).

### Plan announcement (before Step 0)

Before running Step 0, print the following plan to the user verbatim so they know what's about to happen:

> Running **entropy-data-publish**. I'll:
> 1. Verify the `entropy-data` CLI is installed and connected.
> 2. Confirm this is a Databricks bundle and pick up its name.
> 3. Audit existing Entropy Data artifacts (ODPS, ODCS, bundle layout, publish workflow, git connections).
> 4. Gather any missing parameters from you (one batched question).
> 5. Apply fixes — create missing files, patch incomplete ones, register git connections.
> 6. Summarize what changed and what's deferred.

Then proceed.

### Step 0 — Verify the Entropy Data CLI connection

Confirm `uv run --quiet entropy-data --version` succeeds from the project root. If it fails, run `uv sync` (the init template seeds `entropy-data` as a dev dep) and retry. If still missing, stop and tell the user to verify `entropy-data` is in `pyproject.toml`'s `[dependency-groups].dev`. Use `uv run entropy-data …` for every CLI invocation in this skill.

Run `entropy-data connection test`. If it fails (no connection, expired key, etc.), stop and tell the user to run `entropy-data connection add <name> --host <host> --api-key <key>` first. Do not prompt for the key yourself.

### Step 1 — Confirm this is a Databricks bundle

Check that `databricks.yml` exists at the working directory root. If not, stop and tell the user this skill only works inside a Declarative Automation Bundle.

Read `databricks.yml` and remember the `bundle.name:` value — call it `BUNDLE_NAME`. By convention it is also the data product id.

### Step 2 — Audit

For each row in the table above, check whether the artifact is present. For row 6 (git connections), call:

- `entropy-data dataproducts gitconnection get <DATA_PRODUCT_ID> -o json`
- `entropy-data datacontracts gitconnection get <CONTRACT_ID> -o json` for each output-port contract under `src/output_ports/**/`

For rows 2 and 3, glob the file system:

- Output contracts: `src/output_ports/**/*.odcs.yaml`
- Input contracts: `src/input_ports/*.odcs.yaml`

If a `get` returns a 404 (or "not found"), mark that connection as missing. If it returns a connection whose `repository-url` / `repository-path` / `repository-branch` does not match the local repo, mark it as **drifted** and call it out separately — do not silently overwrite. If the underlying data product or contract doesn't exist on the platform yet (the workflow hasn't run for the first time), or if the working directory is not a git repository (`git rev-parse --is-inside-work-tree` errors or returns `false`), mark git connections as **deferred** with a one-line explanation.

For row 1 (ODPS file), also check that the top-level `customProperties` list contains an entry with `property: "dataProductBuilder"` and `value: "https://github.com/entropy-data/dataproduct-builder-databricks"`. If the file exists but the property is missing, mark the ODPS as **incomplete** with a one-line note ("missing dataProductBuilder customProperty"); Step 4 will add it without touching other fields. Forks of this plugin should substitute their own builder URL in the template before publishing.

Produce a short audit report like:

```
Entropy Data integration audit for <BUNDLE_NAME>:
  [✓] ODPS file
  [✗] Output-port contracts (no *.odcs.yaml under src/output_ports/)
  [⏸] Input-port contracts (none — populated by dataproduct-implement from access agreements)
  [✗] Bundle layout (no src/output_ports)
  [✗] GitHub Actions publish workflow
  [⏸] Git connections (deferred: data product not yet published — run the workflow first)
```

Show the report. Then list what you intend to create. **Wait for the user to confirm before writing any files.**

### Step 3 — Gather parameters (only ask for what you cannot infer)

Before generating files, fill in these placeholders. Infer from the project where you can; ask the user for the rest in one batched question.

| Placeholder | Default / inference | Notes |
|---|---|---|
| `DATA_PRODUCT_ID` | `BUNDLE_NAME` | Used as `id` in ODPS |
| `DATA_PRODUCT_NAME` | Title-cased `BUNDLE_NAME` | Human-friendly name |
| `OUTPUT_PORT_NAME` | If any `src/output_ports/v*/*.odcs.yaml` exists, read `schema[0].name` from it. Otherwise the last segment of `BUNDLE_NAME` | One output port per ODCS file. The port name should match the table name, not the bundle name |
| `CONTRACT_ID` | If `src/output_ports/v*/*.odcs.yaml` exists, read its `id:` field. Otherwise `<DATA_PRODUCT_ID>-v1` | Stable id used by `entropy-data datacontracts put`. When a contract was preloaded from Entropy Data (by `dataproduct-init` or `dataproduct-implement`), do NOT mint a fresh `<DATA_PRODUCT_ID>-v1` id — use the existing one |
| `CONTRACT_FILE` | If a preloaded ODCS exists, its filename. Otherwise `<CONTRACT_ID>.odcs.yaml` | File under `src/output_ports/v1/` |
| `CONTRACT_PATH` | If a preloaded ODCS exists, its actual path. Otherwise `src/output_ports/v1/<CONTRACT_FILE>` | Full repo-relative path; used by `--repository-path`, the CI workflow, and `datacontract test` |
| `TABLE` | If a preloaded ODCS exists, its `schema[0].name`. Otherwise the last segment of `BUNDLE_NAME` | Output table name |
| `PURPOSE` | — | Ask the user (one sentence) |
| `TEAM_NAME` | — | If `<DATA_PRODUCT_ID>.odps.yaml` already exists with a `team.name`, use that. Otherwise, prefer a team `id` registered in Entropy Data — invoke the **entropy-data-teams** skill (in this same plugin) so the user can pick from the existing teams, and use the returned `id`. Fall back to a free-text answer only if `entropy-data-teams` cannot run (CLI unavailable / not authenticated) |
| `TAG` | — | Ask the user (e.g. a `usecases/...` slug) |
| `CATALOG` | If a single pipeline resource is defined under `resources/`, take `var.catalog` from `databricks.yml`; else ask | Unity Catalog catalog |
| `SCHEMA` | Same — take `var.schema`; else ask | Unity Catalog schema |
| `ODPS_FILE` | `<DATA_PRODUCT_ID>.odps.yaml` | Path passed to `entropy-data dataproducts put` |
| `API_HOST` | `entropy-data connection get -o json` → `host` | Resolve in Step 4, only when writing the workflow. Uses the same host the CLI is authenticated against, so CI publish hits the same deployment |
| `GIT_REPOSITORY_URL` | `git remote get-url origin` | Used by `gitconnection put`. If no `origin`, ask the user; if the remote is `git@…` SSH form, convert to the equivalent HTTPS URL the platform expects |
| `GIT_REPOSITORY_BRANCH` | `git rev-parse --abbrev-ref HEAD`, falling back to `main` | Used by `gitconnection put`; if HEAD is detached, ask the user |
| `GIT_CONNECTION_TYPE` | inferred from `GIT_REPOSITORY_URL`: `github.com` → `github`, `gitlab.com` → `gitlab`, `bitbucket.org` → `bitbucket`, `dev.azure.com` / `*.visualstudio.com` → `azuredevops` | Ask the user only if the host doesn't match any of these |
| `GIT_HOST` | the URL host, **only when self-hosted** (i.e. not one of the SaaS hosts above); otherwise omit | Passed as `--host` to `gitconnection put` |
| `GIT_CREDENTIAL_EXTERNAL_ID` | — | Optional. Ask the user; if they don't have one yet, leave the connection unauthenticated (it can still be used for read-only metadata in the UI) |

### Step 4 — Apply the fixes

For each missing artifact, copy the corresponding template from `${PLUGIN_ROOT}/skills/entropy-data-publish/templates/` into the user's project, substituting placeholders. Do **not** overwrite existing files; if a file is present but incomplete, surface the diff and ask before changing.

When (and only when) you're about to write `.github/workflows/data-product.yml`, resolve `API_HOST` from the active CLI connection:

```
entropy-data connection get -o json
```

Use the `host` field to substitute `{{API_HOST}}` in the template. Self-hosted deployments are handled via `entropy-data connection add --host <host>`, not a plugin-level setting.

If the ODPS file exists but was flagged as **incomplete — missing dataProductBuilder customProperty** in Step 2, append the entry to the top-level `customProperties` list (do not reorder or touch other entries):

```yaml
customProperties:
  - property: "dataProductBuilder"
    value: "https://github.com/entropy-data/dataproduct-builder-databricks"
```

Surface the diff and ask before saving.

The templates live at:

- `templates/data-product.odps.yaml` → write to `<DATA_PRODUCT_ID>.odps.yaml`
- `templates/src/output_ports/v1/contract.odcs.yaml` → write to `<CONTRACT_PATH>` (i.e. `src/output_ports/v1/<CONTRACT_FILE>`)
- `templates/.github/workflows/data-product.yml` → write to `.github/workflows/data-product.yml`

For the bundle layout, create the directories `src/input_ports/`, `src/transformations/`, `src/output_ports/v1/` if absent, with `.gitkeep` files so the directories survive an empty commit. Do not move existing Python files — only add the empty subfolders the user is missing, and note it in the report.

If `resources/` does not contain any pipeline resource file, that's likely an unfinished init. Flag it as a separate row (`[?] Pipeline resource`) and suggest running `dataproduct-init` or adding a pipeline resource by hand. Do not generate one here.

#### Step 4b — Configure git connections

Only run this sub-step if the audit (Step 2) flagged at least one git connection as **missing** or the user confirmed re-creating a **drifted** one. Skip entirely if every connection is already correct, if the audit marked them as **deferred**, or if the working directory is not a git repository (check with `git rev-parse --is-inside-work-tree` — if it errors or returns `false`, there's no remote to register; tell the user to run `git init` and add a remote first, then re-run this skill).

For the data product:

```
entropy-data dataproducts gitconnection put <DATA_PRODUCT_ID> \
  --repository-url <GIT_REPOSITORY_URL> \
  --repository-path <ODPS_FILE> \
  --repository-branch <GIT_REPOSITORY_BRANCH> \
  --git-connection-type <GIT_CONNECTION_TYPE> \
  [--host <GIT_HOST>] \
  [--git-credential-external-id <GIT_CREDENTIAL_EXTERNAL_ID>]
```

For each output-port ODCS file (`src/output_ports/**/*.odcs.yaml`):

```
entropy-data datacontracts gitconnection put <CONTRACT_ID> \
  --repository-url <GIT_REPOSITORY_URL> \
  --repository-path <CONTRACT_PATH> \
  --repository-branch <GIT_REPOSITORY_BRANCH> \
  --git-connection-type <GIT_CONNECTION_TYPE> \
  [--host <GIT_HOST>] \
  [--git-credential-external-id <GIT_CREDENTIAL_EXTERNAL_ID>]
```

Do **not** register git connections for input-port ODCS files. They are cached copies of upstream contracts; the upstream data product owns the canonical record.

Notes:

- `--repository-path` is **relative to the repo root**, not the working directory. The ODPS path is just `<DATA_PRODUCT_ID>.odps.yaml`; output-port contract paths look like `src/output_ports/v<N>/<CONTRACT_FILE>`.
- Omit `--host` for SaaS providers (github.com, gitlab.com, bitbucket.org, dev.azure.com); set it only for self-hosted instances.
- These commands fail if the underlying data product / contract does not exist on the platform yet. If you skipped earlier because of "deferred," surface the manual command in Step 5 so the user can run it after the first workflow run. Do not retry-loop.
- If the audit reported drift (existing connection with different URL/branch/path), confirm with the user before overwriting — `put` is upsert.

### Step 5 — Final report

Always end with this exact two-part format so the user gets a consistent recap.

**Part 1 — outcome table.** One row per artifact from the audit. Use the `Status` enum below; `Details` is a short, plain-text note (file path, or "—" if nothing to add).

| Artifact | Status | Details |
|---|---|---|
| ODPS file | … | … |
| Output-port contracts | … | `<N>` file(s) at `src/output_ports/v<N>/<CONTRACT_FILE>` |
| Input-port contracts | … | `<N>` file(s) at `src/input_ports/<provider-output-port-id>.odcs.yaml` (or "—" if no access agreements yet) |
| Bundle layout | … | … |
| Publish workflow | … | … |
| Git connections | … | … |

`Status` enum (use exactly these words):

- `created` — the skill wrote a new file or registered a new connection.
- `updated` — the skill patched an existing file or fixed a drifted connection.
- `already present` — no change needed.
- `deferred` — skipped intentionally (data product/contract not yet published, or no git repo). The deferred command(s) appear in Part 2.
- `skipped` — the user declined when asked to confirm.

**Part 2 — next steps.** This skill sits in the middle of the canonical lifecycle (see AGENTS.md § Lifecycle). Include only the items that apply.

> The commands below use `gh` (GitHub CLI) and a `.github/workflows/` CI surface — the plugin's default shape. **Forks** for organizations on GitLab / Azure DevOps / Bitbucket replace `gh` with the equivalent CLI (`glab`, `az devops`, etc.) and swap `.github/workflows/data-product.yml` for the matching pipeline format.


Pre-first-CI-publish (the data product / contract do not exist on the platform yet):

```bash
# (1) Set CI secrets so the workflow can authenticate.
gh secret set DATABRICKS_HOST                --body "<workspace-url>"
gh secret set DATABRICKS_CLIENT_ID           --body "<service-principal-app-id>"
gh secret set DATABRICKS_CLIENT_SECRET       --body "<service-principal-secret>"
gh secret set ENTROPY_DATA_API_KEY           --body "<entropy-data-api-key>"
gh secret set DATACONTRACT_DATABRICKS_TOKEN  --body "<personal-access-token>"
gh secret set DATACONTRACT_DATABRICKS_HTTP_PATH --body "/sql/1.0/warehouses/<warehouse-id>"
# PAT-auth alternative: swap CLIENT_ID/CLIENT_SECRET in the workflow for a
# single DATABRICKS_TOKEN secret.

# (2) Before the first prod deploy, edit databricks.yml: replace
#     `run_as.service_principal_name: <fill-in-before-prod-deploy>` with the
#     CI service principal's application id.

# (3) Push to main → CI publishes the data product + contracts for the first
#     time. Come back to this skill afterwards to register git connections
#     (Step 4b reruns idempotently and registers what was deferred).
```

Post-first-CI-publish (the data product / contract now exist on the platform):

```bash
# For each `deferred` git connection from Part 1's audit, run the exact
# command surfaced by Step 4b — example shape:
entropy-data dataproducts gitconnection put <DATA_PRODUCT_ID> \
  --repository-url <git-url> \
  --repository-path <ODPS_FILE> \
  --repository-branch <branch> \
  --git-connection-type <github|gitlab|bitbucket|azuredevops>

entropy-data datacontracts gitconnection put <CONTRACT_ID> \
  --repository-url <git-url> \
  --repository-path <CONTRACT_PATH> \
  --repository-branch <branch> \
  --git-connection-type <github|gitlab|bitbucket|azuredevops>
```

Other follow-ups:

- "Fill in the data contract schema in `<CONTRACT_PATH>` — the template only seeds `id` and `updated_at`."
- "Run `dataproduct-implement <data-product-url-or-id>` to derive output-port table definitions from the contract."
- "Request access agreements for any upstream input ports — `entropy-data access request <provider-dp-id> <provider-output-port-id> --consumer-dataproduct <DATA_PRODUCT_ID> --purpose <one-sentence>`. Once approved, re-run `dataproduct-implement` to wire them."

If there is nothing in Part 2, write a single line: `No further action required.`

## Conventions and constraints

- **No invented schema**: when generating the ODCS file, do not invent columns. Seed it with `id` + `updated_at` and tell the user to fill in the rest, or — if `@dp.materialized_view` / `@dp.table` definitions already exist for the output port — derive columns from the decorator schema if available.
- **Idempotent**: running the skill a second time should be a no-op when everything is already present. For git connections that means: if `gitconnection get` returns a record matching the local repo URL / branch / path, do not call `put`.
- **Don't overwrite drifted git connections silently.** If the platform reports a different URL/branch/path than the local repo, surface the diff and ask. The user may have a fork, a renamed default branch, or a deliberate path remap.
- **Don't push secrets**: never write API keys, tokens, or workspace URLs into committed files. They must come from GitHub secrets in the workflow.
- **Don't create a git repo or commit**: leave VCS state to the user.
