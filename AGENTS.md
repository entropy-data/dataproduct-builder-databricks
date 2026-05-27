# dataproduct-builder-databricks — agent manifest

> **This file is the plugin's authoritative routing manifest, not a template.** It lives at the plugin's repo root and is meant to be **referenced** from your project (e.g. via Codex CLI's marketplace install, or a one-line pointer in your project's own `AGENTS.md`), not copied into your project. Updating the plugin updates this file in place.

This repository is a coding-agent plugin that helps build data products on Databricks with **Declarative Automation Bundles** (formerly Asset Bundles) and **Lakeflow Spark Declarative Pipelines** (formerly Delta Live Tables), integrated with [Entropy Data](https://entropy-data.com). It exposes its capabilities as **skills** — markdown files under `skills/<name>/SKILL.md` that you read top-to-bottom and execute step by step.

When a user request matches a skill's trigger, **read the corresponding `SKILL.md` start to finish before acting.** Each skill contains audit steps, parameter-gathering, and explicit user-confirmation gates that must not be skipped.

## Skills

| When the user asks about… | Follow this skill |
|---|---|
| Scaffolding a brand-new Databricks data product from scratch (greenfield, empty directory) | `skills/dataproduct-init/SKILL.md` |
| Implementing a data product from a published Entropy Data URL or id — derive `@dp.materialized_view` / `@dp.table` pipelines from the ODCS schema | `skills/dataproduct-implement/SKILL.md` |
| Validating, deploying, and running the bundle's Lakeflow pipeline (`databricks bundle deploy` + `databricks bundle run`) | `skills/dataproduct-deploy/SKILL.md` |
| Granting access to approved consumers — Unity Catalog `GRANT SELECT` (internal) or Delta Sharing (external) | `skills/dataproduct-share/SKILL.md` |
| Auditing an existing Databricks bundle against the Entropy Data layout and adding what's missing (ODPS, ODCS, CI workflow, git connections) | `skills/entropy-data-publish/SKILL.md` |
| Editing an output-port data contract (`src/output_ports/v<N>/*.odcs.yaml`) and testing whether the change is breaking | `skills/datacontract-edit/SKILL.md` |
| Testing existing data contracts against the live warehouse (no edits — just run `datacontract test`) | `skills/datacontract-test/SKILL.md` |
| Uploading example / sample rows for a data product to Entropy Data | `skills/dataproduct-exampledata/SKILL.md` |
| Listing teams in Entropy Data (e.g. to pick `TEAM_NAME` as the data product owner) | `skills/entropy-data-teams/SKILL.md` |

The trigger phrasing above is illustrative; each `SKILL.md`'s frontmatter `description` is authoritative. Skills can also call other skills — e.g. `dataproduct-init` hands off to `entropy-data-publish`. Platform-touching skills verify the `entropy-data` CLI connection with `entropy-data connection test` and the Databricks workspace auth with `databricks auth describe` as their Step 0 and abort if either fails; they do not prompt for credentials themselves.

## Resolving `${PLUGIN_ROOT}`

The skill files reference `${PLUGIN_ROOT}` to locate `templates/`. On Claude Code this is set automatically as `${CLAUDE_PLUGIN_ROOT}`; on Codex / Cursor / other agents reading this file, it is **not** set — resolve it as **the directory that contains this `AGENTS.md`** (the cloned repo root, which also contains `skills/`).

## CLIs the skills shell out to

- **`databricks`** ([installation](https://docs.databricks.com/aws/en/dev-tools/cli/install)) — used to scaffold the bundle (`databricks bundle init`), validate (`databricks bundle validate`), deploy and run (`databricks bundle deploy` / `databricks bundle run`), and apply Unity Catalog grants and Delta Shares. Auth is via `.databrickscfg` profile, `DATABRICKS_HOST` + `DATABRICKS_TOKEN`, or OAuth (`databricks auth login`).
- **`entropy-data`** (PyPI: `entropy-data`; install with `uv tool install entropy-data`) — used to publish data products / contracts, configure git connections, list teams, upload example data, and resolve access agreements. Auth is API-key based (`ENTROPY_DATA_API_KEY` env var, `--api-key` flag, or `entropy-data connection add` storing keys in `~/.entropy-data/config.toml`).
- **`datacontract`** ([Data Contract CLI](https://github.com/datacontract/datacontract-cli); install with `uv tool install 'datacontract-cli[all]'`) — used to lint ODCS files (via PostToolUse hook), test schema and quality rules against the warehouse, and classify edits as breaking or additive.

If any CLI is missing, surface the install instruction and stop — do not try to install on the user's behalf without confirmation.

## Conventions for derived values

### Deriving `DATA_PRODUCT_ID` from a contract id

When a skill is given a published data contract id (not a data product id) — e.g. the user spec'd the schema first in the contract editor and there is no draft data product yet — derive the bundle / data product id from the contract id by:

1. Stripping a trailing version suffix `-v\d+` (or `_v\d+`).
2. Lowercasing.
3. Replacing `-` with `_`.
4. Prepending `dp_` if not already present.

Example: `entropydata-customer-onboarding-v1` → `dp_entropydata_customer_onboarding`.

The derived id must satisfy the same Unity Catalog rules as any hand-picked id: lowercase, snake_case, no hyphens. Confirm with the user before using it as the bundle name.

`dataproduct-init` Step 2b and `dataproduct-implement` Step 1 both apply this rule.

## Conventions when running skills

- **Don't skip the audit.** Skills that modify the project audit existing state first and ask the user to confirm before writing.
- **Don't overwrite existing files silently.** When a target file is present but differs, surface the diff and ask.
- **Don't run `git init`, commit, or push** on the user's behalf — leave VCS state to the user unless the skill explicitly says otherwise.
- **Don't commit secrets.** API keys, tokens, and workspace URLs must come from env vars or repo secrets, never from committed files.
- **Idempotent re-runs.** Running a skill a second time when everything is already in place should be a no-op.
- **Unity Catalog three-part naming.** Tables are addressed as `<catalog>.<schema>.<table>` everywhere — in `databricks.yml` variables, in `@dp.table` references, in ODCS server blocks. Never assume a two-part default.
