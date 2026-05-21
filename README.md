# dataproduct-builder-databricks

Skills for your favorite coding agent that build data products on **Databricks** with [Declarative Automation Bundles](https://docs.databricks.com/aws/en/dev-tools/bundles/) and [Lakeflow Spark Declarative Pipelines](https://docs.databricks.com/aws/en/dlt/), integrated with [Entropy Data](https://entropy-data.com).

Sibling plugin to [dataproduct-builder-dbt](https://github.com/entropy-data/dataproduct-builder-dbt). Pick the one that matches your stack.

It also supports a contract-driven approach: specify your requirements as a [data contract](https://datacontract.com), and the builder implements the data product in minutes.

## Skills

The plugin ships nine skills:

- **dataproduct-init** scaffolds a new Databricks bundle from scratch: `databricks.yml`, a serverless Lakeflow pipeline resource, a Lakeflow Job that schedules it, the `src/{input_ports,transformations,output_ports/v1}/` layout, `pyproject.toml`, README. Shells out to `databricks bundle init lakeflow-pipelines` and overlays the Entropy Data pieces on top.
- **dataproduct-implement** analyzes the input and output data contracts, generates `@dp.table` Python files under `src/output_ports/v1/`, resolves access agreements into `@dp.view` input ports under `src/input_ports/`, and runs `databricks bundle validate` to verify the result.
- **dataproduct-deploy** wraps `databricks bundle validate` → `deploy` → `run` with target selection and polls the pipeline run for completion.
- **dataproduct-share** reads `entropy-data access list --provider-dataproduct` and applies Unity Catalog `GRANT SELECT` for internal consumers or creates a Delta Share for external ones, per active access agreement.
- **entropy-data-publish** audits an existing bundle against the Entropy Data reference layout, adds missing ODPS/ODCS files, generates the GitHub Actions publish workflow, and registers git connections.
- **datacontract-edit** edits an output-port `src/output_ports/v<N>/*.odcs.yaml` using natural language and classifies the change as breaking or additive.
- **datacontract-test** runs `datacontract test` to verify the live data still matches the schema and quality rules.
- **dataproduct-exampledata** extracts sample rows, drops PII columns flagged in the contract, and uploads the scrubbed sample to Entropy Data.
- **entropy-data-teams** lists the teams configured in Entropy Data so the user can pick an owner.

## Install

The skills are plain markdown, any coding agent that can read instruction files can run them.

For major coding agents, those can be installed as a plugin:

### Claude Code

In your terminal:

```
claude plugin marketplace add https://github.com/entropy-data/dataproduct-builder-databricks
claude plugin install dataproduct-builder-databricks@dataproduct-builder-databricks -s project
```

### OpenAI Codex

In your terminal:

```
codex plugin marketplace add https://github.com/entropy-data/dataproduct-builder-databricks
codex plugin add dataproduct-builder-databricks@dataproduct-builder-databricks
```

### GitHub Copilot CLI

In your terminal:

```
copilot plugin marketplace add https://github.com/entropy-data/dataproduct-builder-databricks
copilot plugin install dataproduct-builder-databricks@dataproduct-builder-databricks
```

### Other agents (Cursor, Aider, etc.)

Any agent that reads `AGENTS.md` picks up the routing manifest. Alternatively, copy the `skills` to the directory that your coding agent expects.

### Connect

The skills authenticate against three systems. Configure each once.

**Databricks** — workspace auth via the Databricks CLI:

```
brew install databricks/tap/databricks
databricks auth login --host https://<your-workspace>.cloud.databricks.com
```

**Entropy Data** — API key registered with the [entropy-data CLI](https://github.com/entropy-data/entropy-data-cli) (requires [uv](https://docs.astral.sh/uv/)):

```
uv tool install --upgrade entropy-data
entropy-data connection add default --api-key <your-api-key> --host <your-entropy-data-host>
```

Create a user-scoped key in the Entropy Data web UI (**Organization Settings → API Keys → Create new API key**, scope `User (personal token)`). For CI workflows, add a connection with a team-scoped or organization-scoped key.

**Data Contract CLI** — for `datacontract-edit` and `datacontract-test`:

```
uv tool install 'datacontract-cli[all]'
```

## Use

Ask the agent:

> Initialize the data product *url or id or new name*.

Or:

> Add the property *name* to the data contract and find data products that we could use as input ports. Request access and implement the Lakeflow pipeline.

## Customization

Organizations with their own data-product stack and naming conventions are encouraged to **fork or copy this repository** and adapt it to their environment.

Common extension points:

- **Templates** under [`skills/dataproduct-init/templates/`](skills/dataproduct-init/templates/) and [`skills/entropy-data-publish/templates/`](skills/entropy-data-publish/templates/) ship the ODPS, ODCS, GitHub Actions workflow, and bundle overlay that the init and publish skills install. Replace any of them to match your conventions (e.g. swap GitHub Actions for Azure DevOps, change the layer naming, embed company-specific tags).
- **Skills**: add your own `skills/<name>/SKILL.md` for stack-specific flows (data-quality checks against your standards, governance approvals, downstream sync to your data catalog, etc.). Update `AGENTS.md` and `.github/copilot-instructions.md` so the routing tables surface them.
- **Hooks**: extend [`hooks/hooks.json`](hooks/hooks.json) with additional `PostToolUse` validators (e.g. a `databricks bundle validate` check on every `databricks.yml` edit).

After customizing, rename the plugin in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) and [`.codex-plugin/plugin.json`](.codex-plugin/plugin.json), then publish under your own GitHub organization or GitLab repository.

If a change you've made is broadly useful, [open an issue or PR upstream](https://github.com/entropy-data/dataproduct-builder-databricks/issues); generic improvements are very welcome.

## License

MIT
