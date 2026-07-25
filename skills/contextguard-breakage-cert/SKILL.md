---
name: contextguard-breakage-cert
description: >
  Issue a Query-Aware Breakage Certificate for a proposed schema/dbt change using
  DataHub MCP evidence. Classifies known queries as BREAKS/SAFE/UNKNOWN, emits
  consumer patches, and decides whether merge is allowed. This goes beyond DataHub
  Impact Analysis (dependents list) by proving query breakage.
metadata:
  author: ContextGuard
  version: "0.1.0"
  tags:
    - datahub
    - mcp
    - lineage
    - schema-change
    - governance
---

# ContextGuard Breakage Certificate Skill

## When to use

Use this skill when the user proposes a **schema or dbt model change** and needs:

- proof of which **known DataHub queries** will break
- consumer patches + compatibility SQL
- a merge go/no-go decision (`merge_allowed`)

Do **not** treat DataHub lineage alone as sufficient. Lineage lists dependents; this skill issues a certificate.

## Required DataHub tools

Read (analysis):

- `search`
- `get_entities`
- `list_schema_fields`
- `get_lineage` (DOWNSTREAM)
- `get_dataset_queries`  ← load-bearing for certificates

Write (only after explicit user confirmation):

- `save_document`
- `add_tags` with `contextguard-certificate`

## Workflow

1. Parse the proposed change into one of:
   - `drop_column` / `rename_column` / `type_change` / `model_sql_replacement`
2. Resolve the asset URN in DataHub; abort if unresolved.
3. Collect schema, downstream lineage, owners, quality, and **known queries**.
4. For each known query, deterministically classify:
   - `BREAKS` — query references dropped/renamed/riskily retyped columns (or removed model columns)
   - `SAFE` — proven not to reference the change
   - `UNKNOWN` — insufficient evidence (never invent)
5. Build `cgcert/v1` certificate with `merge_allowed = (BREAKS == 0)`.
6. Emit artifacts: certificate markdown/JSON, consumer patches, compatibility SQL, dbt tests, owner messages.
7. Write-back only if the user confirms — save certificate document + tag.

## Output contract

Always produce:

```json
{
  "version": "cgcert/v1",
  "asset_urn": "...",
  "merge_allowed": false,
  "summary": {"breaks": 1, "safe": 1, "unknown": 0},
  "queries": [
    {
      "verdict": "BREAKS",
      "reason": "...",
      "evidence_urns": ["urn:..."],
      "suggested_patch": "..."
    }
  ]
}
```

Every BREAKS/SAFE claim must include `evidence_urns`. Missing metadata → `UNKNOWN`, never a fabricated dependent.

## CI gate

```bash
contextguard check path/to/breakage_certificate.json
# override: --allow-breakage  (or PR label allow-breakage)
```

## Reference implementation

See the ContextGuard repo: Streamlit app, `contextguard check`, and `examples/`.
