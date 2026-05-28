# {{DATA_PRODUCT_NAME}}

Databricks data product `{{DATA_PRODUCT_ID}}`. Published to [Entropy Data](https://entropy-data.com).

Built with [Declarative Automation Bundles](https://docs.databricks.com/aws/en/dev-tools/bundles/) and [Lakeflow Spark Declarative Pipelines](https://docs.databricks.com/aws/en/ldp/).

## Install

Project Python deps (including the `entropy-data` and `datacontract` CLIs):

```bash
uv sync
```

`uv sync` creates `.venv/` with everything from `pyproject.toml`'s `[dependency-groups].dev`. All invocations below use the venv via `uv run` — no activation needed.

The Databricks CLI is installed separately (it's not a Python package). On macOS:

```bash
brew install databricks/tap/databricks
```

## Configure

Databricks CLI auth (workspace-level, not Python — installed above):

```bash
databricks auth login --host https://<workspace>.cloud.databricks.com
```

Entropy Data CLI auth (writes to `~/.entropy-data/config.toml` — once per machine):

```bash
uv run entropy-data connection add default --api-key <key> --host <host>
```

Set up the contract-test credentials (only needed locally; CI uses repo secrets — see [Publishing](#publishing)). The `datacontract` CLI is a separate tool and does not share auth state with the `databricks` CLI, so a token must be supplied explicitly.

**Recommended — short-lived OAuth from the already-authenticated `databricks` CLI:**

```bash
export DATACONTRACT_DATABRICKS_TOKEN=$(databricks auth token | jq -r .access_token)
export DATACONTRACT_DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/<warehouse-id>
```

The OAuth token is valid for ~1 hour and the literal value never lands in shell history — much smaller leak blast radius than a long-lived PAT, same workspace permissions.

**Fallback — Personal Access Token**, useful when `databricks auth token` isn't available (e.g. PAT-only profile, OAuth refresh issue, headless shell):

```bash
export DATACONTRACT_DATABRICKS_TOKEN=<personal-access-token>
export DATACONTRACT_DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/<warehouse-id>
```

A PAT is long-lived (until rotated). Scope it narrowly (read access to the data product's schema is enough) and avoid putting the `export` in `.bashrc`/`.zshrc` — it persists in shell history.

## Run

```bash
databricks bundle validate --target dev
databricks bundle deploy --target dev
databricks bundle run {{DATA_PRODUCT_ID}} --target dev
```

The `dev` target is the default — running `databricks bundle deploy` with no `--target` flag picks it. A `prod` target ships as a stub; edit `databricks.yml` to fill in `run_as.service_principal_name` before the first prod deploy.

## Layout

```
src/
├── input_ports/        # @dp.view wrappers over upstream UC tables (one per access agreement)
├── transformations/    # intermediate logic (optional; user-owned)
└── output_ports/v1/    # @dp.materialized_view / @dp.table — contract-governed tables (one per output port)
```

Output ports are versioned (`v1`, `v2`, ...). Each version directory holds the Python files plus the ODCS data contract that governs the schema (`<contract-id>.odcs.yaml`). Cached input-port contracts live in `src/input_ports/` next to their `.py` source.

## Publishing

CI in `.github/workflows/data-product.yml` runs `databricks bundle deploy`, triggers the Lakeflow pipeline, runs the data contract test, and publishes the ODPS + ODCS back to Entropy Data.
