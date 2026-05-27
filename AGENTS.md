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

## Lifecycle: from scaffold to wired pipeline

A new data product reaches "input ports wired, materialized view producing rows" through this canonical loop. Skills cover the marked steps; the rest are intentionally manual (governance, user authority, or both).

1. **Scaffold the bundle.** `dataproduct-init` (greenfield) or `entropy-data-publish` (audit an existing bundle).
2. **Generate stub output ports.** `dataproduct-implement` reads the ODCS, writes `@dp.materialized_view` / `@dp.table` Python with column placeholders and a TODO body (when no input ports are yet wired).
3. **Validate locally.** `databricks bundle validate --target dev` — built into the skills.
4. **Set up version control + CI.** *Manual:* `git init`, `gh repo create`, `gh secret set` for each CI secret, push. The init skill emits the literal commands in its final-report next-steps.
5. **First CI publish.** *Manual trigger (push):* CI workflow runs `entropy-data dataproducts put` and `entropy-data datacontracts put`. This is when the data product first exists on the Entropy Data platform.
6. **Register git connections.** Re-run `entropy-data-publish` from the working directory; its Step 4b detects the now-present platform records and registers `dataproducts gitconnection put` + `datacontracts gitconnection put`.
7. **Request access agreements for input ports.** *Manual:* `entropy-data access request <provider-dp-id> <provider-output-port-id> --consumer-dataproduct <DATA_PRODUCT_ID> --purpose "…"` for each upstream. Business judgement (purpose, port choice, roles) belongs to the user, not the skill.
8. **Wait for approval.** *Manual + async:* the provider team approves via `entropy-data access approve <id>` or the UI.
9. **Wire input ports.** Re-run `dataproduct-implement` — `entropy-data access list --consumer-dataproduct …` now returns active agreements, the skill caches each upstream contract under `src/input_ports/`, writes `@dp.view` wrappers, and attempts 1:1 column matching.
10. **Build transformation logic.** *Manual coding* in `src/output_ports/v1/<table>.py` — joins, aggregations, derived columns, conditional logic. The skill marks each as `# TODO: <description from contract>`.
11. **Deploy + run.** `dataproduct-deploy` validates, deploys, runs, and polls.
12. **Verify against the contract.** `datacontract-test` (skill or direct CLI) — schema + quality checks against the live table.
13. **Share with consumers.** `dataproduct-share` applies Unity Catalog `GRANT SELECT` or sets up Delta Sharing per approved consumer access agreement.

Steps 4-8 are the heaviest manual stretch. Steps 4 (VCS setup) and 7 (access request) are deliberately outside skill scope: VCS has high blast radius and access decisions are governance. Each SKILL.md's final-report next-steps points back to this lifecycle so the user knows where they are in the loop.

## Conventions when running skills

- **Don't skip the audit.** Skills that modify the project audit existing state first and ask the user to confirm before writing.
- **Don't overwrite existing files silently.** When a target file is present but differs, surface the diff and ask.
- **Don't run `git init`, commit, or push** on the user's behalf — leave VCS state to the user unless the skill explicitly says otherwise.
- **Don't commit secrets.** API keys, tokens, and workspace URLs must come from env vars or repo secrets, never from committed files.
- **Idempotent re-runs.** Running a skill a second time when everything is already in place should be a no-op.
- **Unity Catalog three-part naming.** Tables are addressed as `<catalog>.<schema>.<table>` everywhere — in `databricks.yml` variables, in `@dp.table` references, in ODCS server blocks. Never assume a two-part default.
