# ContextGuard architecture

## Components

| Unit | Responsibility |
|------|----------------|
| `contextguard/analysis.py` | Parse MVP change types; deterministic risk score |
| `contextguard/datahub.py` | MCP boundary — read tools vs isolated write path |
| `contextguard/agent.py` | Orchestrate evidence → score → LLM/fallback artifacts; stale-run guard |
| `contextguard/artifacts.py` | Validate SQL refs; package ZIP / example bundles |
| `app.py` | Judge-facing Streamlit workflow |

## Data flow

1. User selects a DataHub asset URN and describes a change (or uploads SQL/dbt).
2. Parser maps input to `drop_column` | `rename_column` | `type_change` | `model_sql_replacement`.
3. MCP read tools fetch schema, downstream lineage, owners, queries, quality signals.
4. Risk engine scores blast radius without the LLM.
5. Gemini (optional) drafts explanations/artifacts strictly from evidence JSON; one repair attempt; else deterministic fallback.
6. User downloads ZIP. Optional write-back saves a review document and tag after explicit confirm.

## Non-goals (MVP)

- GitHub App / automatic PR creation
- Arbitrary DDL beyond the four change types
- Executing SQL against warehouses
