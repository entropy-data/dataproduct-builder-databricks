# {{DATA_PRODUCT_NAME}}

Databricks data product `{{DATA_PRODUCT_ID}}`. Published to [Entropy Data](https://entropy-data.com).

Built with [Declarative Automation Bundles](https://docs.databricks.com/aws/en/dev-tools/bundles/) and [Lakeflow Spark Declarative Pipelines](https://docs.databricks.com/aws/en/dlt/).

## Install

```bash
uv venv
source .venv/bin/activate
uv pip install --group dev
```

## Configure

Authenticate the Databricks CLI:

```bash
databricks auth login --host https://<workspace>.cloud.databricks.com
```

Authenticate the Entropy Data CLI:

```bash
entropy-data connection add default --api-key <key> --host <host>
```

Set up the contract-test credentials (only needed locally; CI uses repo secrets):

```bash
export DATACONTRACT_DATABRICKS_TOKEN=<personal-access-token>
export DATACONTRACT_DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/<warehouse-id>
```

## Run

```bash
databricks bundle validate
databricks bundle deploy --target default
databricks bundle run {{DATA_PRODUCT_ID}} --target default
```

## Layout

```
src/
├── input_ports/        # @dp.view wrappers over upstream UC tables (one per access agreement)
├── transformations/    # intermediate logic (optional; user-owned)
└── output_ports/v1/    # @dp.table — contract-governed tables (one per output port)
```

Output ports are versioned (`v1`, `v2`, ...). Each version directory holds the Python files plus the ODCS data contract that governs the schema (`<contract-id>.odcs.yaml`). Cached input-port contracts live in `src/input_ports/` next to their `.py` source.

## Publishing

CI in `.github/workflows/data-product.yml` runs `databricks bundle deploy`, triggers the Lakeflow pipeline, runs the data contract test, and publishes the ODPS + ODCS back to Entropy Data.
