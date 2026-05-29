#!/usr/bin/env python3
"""Emit an OpenLineage RunEvent for one Databricks output port.

Builds the RunEvent from Unity Catalog metadata and writes it to stdout
so the caller can pipe into `entropy-data lineage submit --file -`.

For each input dataset, the schema facet is **subset to the columns the
pipeline actually consumes** (looked up via `/api/2.0/lineage-tracking/
column-lineage`), so the Lineage panel shows only the relevant fields
on each input card rather than the upstream table's full schema. The
output dataset's schema facet is always the full schema.

Requires `databricks` CLI on PATH and `DATABRICKS_HOST` env var (used
to build the OpenLineage namespace).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

PRODUCER = "https://github.com/entropy-data/dataproduct-builder-databricks"
SCHEMA_FACET_URL = "https://openlineage.io/spec/facets/1-1-0/SchemaDatasetFacet.json"
JOB_TYPE_FACET_URL = "https://openlineage.io/spec/facets/2-0-3/JobTypeJobFacet.json"
RUN_EVENT_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json"


def _db(cmd: list[str]) -> dict:
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def db_api(path: str, body: dict) -> dict:
    return _db(["databricks", "api", "get", path, "--json", json.dumps(body)])


def get_columns(full_name: str) -> list[dict]:
    return _db(["databricks", "tables", "get", full_name, "-o", "json"])["columns"]


def schema_facet(cols: list[dict]) -> dict:
    return {
        "_producer": PRODUCER,
        "_schemaURL": SCHEMA_FACET_URL,
        "fields": [
            {
                "name": c["name"],
                "type": c.get("type_text", ""),
                "description": c.get("comment") or "",
            }
            for c in cols
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data-product-id", required=True)
    p.add_argument("--output-port-name", required=True)
    p.add_argument("--output-table", required=True, help="<catalog>.<schema>.<table>")
    p.add_argument(
        "--databricks-host",
        default=os.environ.get("DATABRICKS_HOST", ""),
        help="Workspace URL; defaults to $DATABRICKS_HOST",
    )
    p.add_argument("--integration", default="LAKEFLOW")
    p.add_argument("--job-type", default="MATERIALIZED_VIEW")
    args = p.parse_args()

    if not args.databricks_host:
        sys.exit("error: --databricks-host or $DATABRICKS_HOST is required")

    host = args.databricks_host.removeprefix("https://").removeprefix("http://").rstrip("/")
    namespace = f"databricks://{host}"
    event_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = str(uuid.uuid4())

    output_cols = get_columns(args.output_table)

    # Per-output-column lineage → map: input-table → set of consumed input-cols.
    used: dict[str, set[str]] = {}
    for col in output_cols:
        cl = db_api(
            "/api/2.0/lineage-tracking/column-lineage",
            {"table_name": args.output_table, "column_name": col["name"]},
        )
        for u in cl.get("upstream_cols", []) or []:
            tbl = f"{u['catalog_name']}.{u['schema_name']}.{u['table_name']}"
            used.setdefault(tbl, set()).add(u["name"])

    # Inputs: take the authoritative upstream list from table-lineage, then
    # for each table either subset to the consumed-columns or — if column-lineage
    # had no record — fall back to the full schema rather than emit an empty one.
    tl = db_api("/api/2.0/lineage-tracking/table-lineage", {"table_name": args.output_table})
    inputs: list[dict] = []
    for u in tl.get("upstreams", []) or []:
        info = u.get("tableInfo") or {}
        if not (info.get("catalog_name") and info.get("schema_name") and info.get("name")):
            continue
        tbl = f"{info['catalog_name']}.{info['schema_name']}.{info['name']}"
        all_cols = get_columns(tbl)
        consumed = used.get(tbl)
        cols = [c for c in all_cols if c["name"] in consumed] if consumed else all_cols
        inputs.append(
            {"namespace": namespace, "name": tbl, "facets": {"schema": schema_facet(cols)}}
        )

    event = {
        "eventType": "COMPLETE",
        "eventTime": event_time,
        "producer": PRODUCER,
        "schemaURL": RUN_EVENT_URL,
        "run": {"runId": run_id},
        "job": {
            "namespace": namespace,
            "name": f"{args.data_product_id}.{args.output_port_name}",
            "facets": {
                "jobType": {
                    "_producer": PRODUCER,
                    "_schemaURL": JOB_TYPE_FACET_URL,
                    "processingType": "BATCH",
                    "integration": args.integration,
                    "jobType": args.job_type,
                }
            },
        },
        "inputs": inputs,
        "outputs": [
            {
                "namespace": namespace,
                "name": args.output_table,
                "facets": {"schema": schema_facet(output_cols)},
            }
        ],
    }

    json.dump(event, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
