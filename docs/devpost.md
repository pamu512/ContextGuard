# Devpost description

## Tagline
Stop breaking dashboards — Query-Aware Breakage Certificates on DataHub.

## Elevator pitch
ContextGuard proves which known DataHub queries die under a schema change, emits consumer patches, and gates merge — beyond Impact Analysis.

## About (short)

DataHub already answers “who depends on this?” ContextGuard answers “which real queries break, how to fix each, and whether you may merge.”

We pull known queries via MCP, deterministically classify each as BREAKS/SAFE/UNKNOWN, issue a versioned `cgcert/v1` certificate, generate compatibility SQL + consumer patches, optionally write the certificate back to the catalog, enforce it in GitHub Actions, and package the workflow as a DataHub Skill.

## Built with
python, streamlit, datahub, mcp, google-adk, gemini, pydantic, pytest, dbt, sql, github-actions

## Try it out
- https://github.com/pamu512/ContextGuard
- Demo mode: `streamlit run app.py`
