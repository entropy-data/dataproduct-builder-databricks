---
name: dataproduct-share
description: Sync approved Entropy Data access agreements to Unity Catalog grants (internal consumers) or Delta Shares (external consumers). Reads `entropy-data access list --provider-dataproduct <id>`, filters to active agreements, and applies `GRANT SELECT` on the output port's table or creates a Delta Share with that table added. Trigger when the user asks to "grant access to consumers", "apply UC grants for approved access", "set up Delta Sharing for this product", or "sync access agreements to Databricks".
---

# Sync access agreements to Unity Catalog grants and Delta Shares

This data product is a **provider** — other products consume from it. Entropy Data tracks access agreements where the access has been approved; until the grant lands in Unity Catalog (or a Delta Share is created), the consumer can see the data product in the catalog but cannot actually `SELECT` from it. This skill closes that gap.

Two delivery mechanisms, chosen per agreement:

- **Internal consumer** (same Databricks account, identified by a principal id, group, or service-principal id) → `GRANT SELECT ON TABLE <catalog>.<schema>.<table> TO <principal>`. Native Unity Catalog, no separate sharing object.
- **External consumer** (different account or organization, identified by an email or Delta Sharing recipient) → create or update a Delta Share that includes the output port's table; the consumer queries via Delta Sharing client.

## When to use this vs. other skills

- **Consumer just requested access via Entropy Data and it was approved** → this skill.
- **You want to deploy code changes** → `dataproduct-deploy`. Grants are independent of bundle deployment.
- **You want to revoke access** → not yet supported; surface the manual `databricks grants update --json '{"changes":[{"principal":"...","remove":["SELECT"]}]}'` or `databricks shares update --remove-table ...` command and stop.

## How to run this skill

> `${PLUGIN_ROOT}` below refers to the root of this plugin — the directory that contains `skills/`. On Claude Code it is set automatically as `${CLAUDE_PLUGIN_ROOT}` — use that. On any other agent (Codex, Copilot CLI, etc.) it is unset; resolve it as `../..` relative to **this `SKILL.md` file's directory** (i.e. the grandparent of `skills/<this-skill>/`).

### Plan announcement (before Step 0)

Before running Step 0, print this plan to the user verbatim:

> Running **dataproduct-share**. I'll:
> 1. Pre-checks: confirm this is a bundle, the `databricks` CLI is authenticated with grant permission, and the `entropy-data` CLI is connected.
> 2. Resolve the data product id from `<id>.odps.yaml` (or ask).
> 3. List approved access agreements where this product is the provider.
> 4. Classify each as **internal** (UC grant) or **external** (Delta Share). Ask if unclear.
> 5. Build a grant/share plan, show it to you. **Wait for your confirmation.**
> 6. Apply grants with `databricks grants update`; create/update shares with `databricks shares` commands.
> 7. Report what was applied, what failed, what's already in place.

Then proceed.

### Step 0 — Pre-checks

- Confirm `databricks.yml` exists at the working directory root.
- Confirm `databricks --version` is on PATH and `databricks auth describe` succeeds. The authenticated identity must have `MANAGE` on the target catalog or `MANAGE GRANT` on the output port's table — `databricks grants get TABLE <catalog>.<schema>.<table>` should succeed. If it fails with a permissions error, surface it and ask the user to either re-auth as a privileged principal or hand off the generated grant commands to someone who can run them.
- Confirm `entropy-data --version` is on PATH and `entropy-data connection test` succeeds.
- Resolve `DATA_PRODUCT_ID`: look for a single `*.odps.yaml` at the repo root and read `id`. If multiple ODPS files exist or none, ask the user.

### Step 1 — List approved access agreements

```
entropy-data access list --provider-dataproduct <DATA_PRODUCT_ID> -o json
```

Keep only entries with `info.active: true` (status `approved`); ignore `pending`, `rejected`, and `revoked`. The remaining entries each describe one consumer relationship; capture for each:

- `consumer.dataProductId` and `consumer.team`
- `consumer.principal` (the workspace-side identity to grant to — may be empty if the agreement was created before this field existed)
- `provider.outputPortId` (which output port of ours they have access to)
- `info.approvedAt`, `info.purpose`

Remember the filtered list as `AGREEMENTS`. If empty, write `No approved access agreements for <DATA_PRODUCT_ID>.` and stop.

Cross-reference each agreement's `provider.outputPortId` against the local `<id>.odps.yaml`. If an agreement references an output port that no longer exists locally (e.g. it was removed or renamed), flag it as **orphaned** and exclude from the plan — surface in the final report.

### Step 2 — Classify internal vs. external

For each agreement, decide the delivery mechanism:

| Consumer signal | Mechanism | Notes |
|---|---|---|
| `consumer.principal` matches `<email>@<your-account-domain>` or a known service-principal id in the same account | **Internal — UC grant** | Use `databricks grants update` |
| `consumer.principal` is a Delta Sharing recipient name (already created) | **External — Delta Share** | Use `databricks shares update --add-table` |
| `consumer.principal` is an email at an unrecognized domain | **External — Delta Share** (create recipient first) | Use `databricks recipients create` then `databricks shares ...` |
| `consumer.principal` is empty | **Ask the user** | "Agreement <id> doesn't specify a principal. Is consumer <consumer.dataProductId> internal (give a UC principal) or external (give a Delta Sharing recipient or email)?" |

To determine "same account": fetch the current workspace's account id once (`databricks current-user me -o json` for the user's identity; for service principals, the account id is in `databricks auth describe -o json`). Treat any principal whose account id matches as internal. Heuristic-fail: if you cannot infer the account, default to **ask the user** rather than guessing.

Record the chosen mechanism per agreement as `MECHANISM[<agreement-id>] = "uc" | "share"`.

### Step 3 — Build the plan and confirm

Print one table per mechanism so the user can review the full plan before anything runs.

**Unity Catalog grants:**

| Agreement | Consumer | Output port | Table | Principal | Action |
|---|---|---|---|---|---|
| `<agreement-id>` | `<consumer.dataProductId>` | `<output-port-id>` | `<catalog>.<schema>.<table>` | `<principal>` | `GRANT SELECT` (already present / new) |

**Delta Shares:**

| Agreement | Consumer | Output port | Table | Share | Recipient | Action |
|---|---|---|---|---|---|---|
| `<agreement-id>` | `<consumer.dataProductId>` | `<output-port-id>` | `<catalog>.<schema>.<table>` | `<share-name>` | `<recipient-name>` | "add table to share" / "create share + add table" / "create recipient + share + add table" |

The share name convention: `<DATA_PRODUCT_ID>_share` (one share per data product; tables added per agreement). If the user prefers per-output-port shares, ask before proceeding.

**Wait for explicit user confirmation before applying anything.**

### Step 4 — Apply

For each Unity Catalog grant in the plan:

1. Check current grants: `databricks grants get TABLE <catalog>.<schema>.<table> -o json`. If `<principal>` already has `SELECT`, mark as `already present` and skip.
2. Apply the grant:

   ```
   databricks grants update TABLE <catalog>.<schema>.<table> \
     --json '{"changes":[{"principal":"<principal>","add":["SELECT"]}]}'
   ```

3. Verify by re-reading grants. If `SELECT` is now present, mark as `created`; otherwise `failed` with the API error.

For each Delta Share in the plan:

1. Ensure the recipient exists. `databricks recipients get <recipient-name> -o json` — if 404, create it:

   ```
   databricks recipients create --json '{"name":"<recipient-name>","authentication_type":"TOKEN"}'
   ```

   For Databricks-to-Databricks sharing (consumer is on Databricks), use `authentication_type: DATABRICKS` instead and pass `data_recipient_global_metastore_id` from the consumer's metastore.
2. Ensure the share exists. `databricks shares get <share-name> -o json` — if 404, create it:

   ```
   databricks shares create --name <share-name>
   ```

3. Add the table to the share if not already present:

   ```
   databricks shares update <share-name> --json '{"updates":[{"action":"ADD","data_object":{"name":"<catalog>.<schema>.<table>","data_object_type":"TABLE"}}]}'
   ```

4. Grant the share to the recipient:

   ```
   databricks shares share-permissions update <share-name> \
     --json '{"changes":[{"principal":"<recipient-name>","add":["SELECT"]}]}'
   ```

5. Mark as `created` (full path), `updated` (table added to existing share), or `already present` (recipient + share + table + permission all already wired).

If any step fails, capture the CLI error and continue to the next agreement — do not abort the run on a single failure, the user will want a full report of what worked and what didn't.

### Step 5 — Report

End with this two-part recap. Use the same `Status` enum (`created`, `updated`, `already present`, `deferred`, `skipped`); for failed grants/shares, use a sixth informal value `failed` in the table cell with the error in `Details`.

**Part 1 — outcome table.** Group rows by mechanism.

| Agreement | Mechanism | Target | Status | Details |
|---|---|---|---|---|
| `<id>` | UC grant | `<catalog>.<schema>.<table>` ← `<principal>` | … | "SELECT added" / "already present" / "failed: <error>" |
| `<id>` | Delta Share | `<share-name>` ⇢ `<recipient-name>` (+ `<table>`) | … | "share created + table added + recipient granted" / "table added to existing share" / "already present" / "failed: <error>" |

Append a sub-table for **orphaned** agreements (active in Entropy Data, but the output port no longer exists locally):

| Agreement | Consumer | Missing output port | Suggested action |
|---|---|---|---|

**Part 2 — next steps.** Bullet list:

- For each `failed` row, the exact CLI command to retry manually with the error context.
- For each new Delta Share, the connection info the consumer needs: recipient name, share name, the activation URL (`databricks recipients get <recipient> -o json` returns `activation_url` for token-auth recipients — surface it but do not share it via email/Slack from this skill).
- For orphaned agreements, suggest the user either restore the output port (if removed accidentally) or revoke the agreement in Entropy Data (the platform doesn't auto-revoke when an output port disappears).
- Remind: re-running this skill is safe and idempotent. If access is later revoked in Entropy Data, **this skill does not remove the grant** — the user must do that manually (link to the revoke command syntax in the "When to use" section above).

If nothing was changed (every agreement was already in place), write a single line: `All <N> active access agreements for <DATA_PRODUCT_ID> are already wired up.`

## Constraints

- **No revoke.** This skill only grants/creates/adds. Revoking access requires explicit user intent and is out of scope here — surface the manual command instead.
- **No silent grants.** Every plan must be confirmed by the user before Step 4 runs. The diff between "what's planned" and "what's already in place" is part of the plan table.
- **No production catalog assumptions.** The table path comes from the output port's `server` block in `<id>.odps.yaml`. If the bundle was last deployed to a dev target but the ODPS server points at the prod catalog, the grants land on prod — flag this explicitly when the targets disagree.
- **Idempotent**: re-running with the same agreement list and the same UC state is a no-op. Failed agreements are retryable individually.
- **Do not store recipient activation URLs in the repo.** They are time-limited bearer tokens. Surface them inline, let the user transfer them out of band.
