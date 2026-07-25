# ContextGuard Winner Wedge Design

**Date:** 2026-07-25  
**Status:** Approved  
**Goal:** Widen the gap vs DataHub Impact Analysis and typical MCP demos.

## Thesis

DataHub answers “who depends on this asset.”  
ContextGuard answers “which real queries die, how to fix each, and whether merge is allowed.”

## Differentiator: Query-Aware Breakage Certificate (`cgcert/v1`)

For a proposed change, ContextGuard:

1. Collects DataHub evidence (schema, lineage, owners, **known queries**, quality).
2. Deterministically classifies each known query as `BREAKS` | `SAFE` | `UNKNOWN`.
3. Emits a versioned certificate + per-query consumer patches + compatibility shim.
4. Optionally writes the certificate back to DataHub as a document + `contextguard-certificate` tag.
5. Enforces the certificate in CI via GitHub Action (`contextguard check`).
6. Packages the workflow as a DataHub Skill for other agents.

## Non-goals

- Full SQL dialect parsing perfection
- Warehouse execution / shadow runs
- Auto-merging PRs without human override

## Components

| Unit | Responsibility |
|------|----------------|
| `query_impact.py` | Classify known queries vs proposed change |
| `certificate.py` | Build/verify `cgcert/v1` JSON + Markdown |
| `agent.py` | Attach certificate to every analysis |
| `cli.py` `check` | Exit non-zero on BREAKS unless allowlisted |
| `.github/workflows/contextguard.yml` | PR merge gate |
| `skills/contextguard-breakage-cert/` | DataHub Skill package |

## Certificate schema (essential fields)

- `version`: `cgcert/v1`
- `run_id`, `asset_urn`, `change`, `risk`
- `queries[]`: `{ query, verdict, reason, evidence_urns, suggested_patch }`
- `summary`: counts of BREAKS/SAFE/UNKNOWN
- `merge_allowed`: false if any BREAKS
- `content_hash`: sha256 of canonical payload (stable identity for write-back)

## Success criteria

- Dropping `amount` marks the sample query BREAKS and produces a patch.
- Safe type change with no referencing queries → merge_allowed true.
- `contextguard check` fails on breaking fixture; passes on safe fixture.
- UI shows certificate table as the primary result.
- Skill README explains the workflow for Claude/Cursor agents.

## Judging narrative

“Beyond Impact Analysis — query proof, merge gate, and an OSS skill.”
