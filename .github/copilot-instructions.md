# dataproduct-builder-databricks — Copilot CLI instructions

> **This file is the plugin's authoritative routing manifest, not a template.** It ships at the plugin's repo root and is loaded automatically when you install the plugin with `/plugin install github.com/entropy-data/dataproduct-builder-databricks`. Don't copy it into your project — when the plugin updates, this file updates with it.

This repository is a coding-agent plugin that helps build data products on Databricks with **Declarative Automation Bundles** and **Lakeflow Spark Declarative Pipelines**, integrated with [Entropy Data](https://entropy-data.com). It exposes its capabilities as **skills** — markdown files under `skills/<name>/SKILL.md` that you read top-to-bottom and execute step by step.

When a user request matches a skill's trigger, **read the corresponding `SKILL.md` start to finish before acting.** Each skill contains audit steps, parameter-gathering, and explicit user-confirmation gates that must not be skipped.

## Skills

| When the user asks about… | Follow this skill |
|---|---|
| Scaffolding a brand-new Databricks data product from scratch (greenfield, empty directory) | `skills/dataproduct-init/SKILL.md` |
| Implementing a data product from a published Entropy Data URL or id — derive `@dp.table` pipelines from the ODCS schema | `skills/dataproduct-implement/SKILL.md` |
| Validating, deploying, and running the bundle's Lakeflow pipeline | `skills/dataproduct-deploy/SKILL.md` |
| Granting access to approved consumers — UC `GRANT SELECT` or Delta Sharing | `skills/dataproduct-share/SKILL.md` |
| Auditing an existing Databricks bundle against the Entropy Data layout | `skills/entropy-data-publish/SKILL.md` |
| Editing an output-port data contract and testing whether the change is breaking | `skills/datacontract-edit/SKILL.md` |
| Testing existing data contracts against the live warehouse | `skills/datacontract-test/SKILL.md` |
| Uploading example / sample rows for a data product to Entropy Data | `skills/dataproduct-exampledata/SKILL.md` |
| Listing teams in Entropy Data | `skills/entropy-data-teams/SKILL.md` |

The trigger phrasing above is illustrative; each `SKILL.md`'s frontmatter `description` is authoritative. Skills can also call other skills — e.g. `dataproduct-init` hands off to `entropy-data-publish`. Platform-touching skills verify the `entropy-data` CLI connection with `entropy-data connection test` and the Databricks workspace auth with `databricks auth describe` as their Step 0 and abort if either fails.

## Resolving `${PLUGIN_ROOT}`

The skill files reference `${PLUGIN_ROOT}` to locate `templates/`. On Claude Code this is set automatically as `${CLAUDE_PLUGIN_ROOT}`; on Copilot CLI it is **not** set — resolve it as the cloned repo root (the directory that contains `skills/`; i.e. the parent of the `.github/` directory containing this file).

## CLIs the skills shell out to

- **`databricks`** — bundle init/validate/deploy/run, UC grants, Delta Sharing. Auth via `.databrickscfg`, env vars, or OAuth.
- **`entropy-data`** (`uv tool install entropy-data`) — publish ODPS/ODCS, git connections, team lookup, example data, access agreement lookup.
- **`datacontract`** (`uv tool install 'datacontract-cli[all]'`) — lint, test, breaking-change classification.

If any CLI is missing, surface the install instruction and stop — do not try to install on the user's behalf without confirmation.

## Conventions when running skills

- **Don't skip the audit.** Skills that modify the project audit existing state first and ask the user to confirm before writing.
- **Don't overwrite existing files silently.** When a target file is present but differs, surface the diff and ask.
- **Don't run `git init`, commit, or push** on the user's behalf — leave VCS state to the user unless the skill explicitly says otherwise.
- **Don't commit secrets.** API keys, tokens, and workspace URLs must come from env vars or repo secrets.
- **Idempotent re-runs.** Running a skill a second time when everything is already in place should be a no-op.
- **Unity Catalog three-part naming.** Tables are `<catalog>.<schema>.<table>` everywhere.
