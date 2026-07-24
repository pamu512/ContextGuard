# Devpost description

## Tagline
Stop breaking dashboards — schema-change safety agent grounded in DataHub.

## Elevator pitch
ContextGuard turns a proposed column drop, rename, type change, or dbt model rewrite into a cited impact report and merge-ready migration pack by reading DataHub lineage, schemas, owners, usage, and quality via MCP — then optionally writing the approved review back to the catalog.

## What it does
- Parses four high-frequency breaking changes
- Collects evidence through DataHub MCP (search, entities, schema, lineage, queries)
- Scores risk deterministically so severity isn’t an LLM hallucination
- Generates compatibility SQL, dbt tests, checklist, and owner pings with URN-cited claims
- Packages a judge-ready ZIP; write-back is explicit and off by default

## How we built it
Python + Streamlit + Pydantic + Google ADK MCP (`StreamableHTTPConnectionParams`) + Gemini 2.5 Flash (optional free tier) with a deterministic artifact fallback for zero-key demos.

## Challenges
Keeping the agent honest: every impact claim must cite DataHub URNs; missing metadata is surfaced as unknown, never invented.

## What's next
PR bot integration, column-level contract diffs, and first-class DataHub Skill packaging.
