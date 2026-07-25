"""ContextGuard Streamlit app — Connect → Select → Analyze → Review/export."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from contextguard.agent import AnalysisOrchestrator, AgentError, StaleRunError
from contextguard.analysis import UnsupportedChangeError
from contextguard.artifacts import package_artifacts_zip
from contextguard.config import Settings, get_settings
from contextguard.datahub import DataHubClient, DataHubError

load_dotenv()

st.set_page_config(
    page_title="ContextGuard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

STEPS = ["Connect", "Select asset", "Analyze change", "Review / export"]


def _run(coro):
    return asyncio.run(coro)


def _settings_from_session() -> Settings:
    return Settings(
        GOOGLE_API_KEY=st.session_state.get("google_api_key")
        or os.getenv("GOOGLE_API_KEY", ""),
        DATAHUB_MCP_URL=st.session_state.get("datahub_mcp_url")
        or os.getenv("DATAHUB_MCP_URL", ""),
        DATAHUB_TOKEN=st.session_state.get("datahub_token") or os.getenv("DATAHUB_TOKEN", ""),
        CONTEXTGUARD_ALLOW_WRITEBACK=bool(
            st.session_state.get("allow_writeback")
            or os.getenv("CONTEXTGUARD_ALLOW_WRITEBACK", "false").lower() == "true"
        ),
    )


class SessionTools:
    """Lazy ADK MCP adapter held in session for reuse."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._caller = None

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        if self._caller is None:
            from contextguard.datahub import AdkMcpToolCaller

            self._caller = AdkMcpToolCaller(self.settings)
            await self._caller.connect()
        return await self._caller.call_tool(name, arguments)


def main() -> None:
    st.title("ContextGuard")
    st.caption(
        "Schema-change safety agent grounded in DataHub lineage, ownership, and usage — "
        "read → reason → act."
    )

    if "step" not in st.session_state:
        st.session_state.step = 0
    if "analysis" not in st.session_state:
        st.session_state.analysis = None

    step = st.session_state.step
    st.progress((step + 1) / len(STEPS), text=STEPS[step])

    cols = st.columns(len(STEPS))
    for i, label in enumerate(STEPS):
        cols[i].markdown(f"**{i + 1}. {label}**" if i == step else f"{i + 1}. {label}")

    if step == 0:
        _step_connect()
    elif step == 1:
        _step_select()
    elif step == 2:
        _step_analyze()
    else:
        _step_review()


def _step_connect() -> None:
    st.subheader("Connect")
    st.markdown(
        "Credentials stay server-side and are never written into exported artifacts. "
        "Leave fields blank to use environment / Streamlit secrets."
    )
    defaults = get_settings()
    mcp_url = st.text_input(
        "DataHub MCP URL",
        value=st.session_state.get("datahub_mcp_url", defaults.datahub_mcp_url),
        help="Example: https://<tenant>.acryl.io/integrations/ai/mcp",
    )
    token = st.text_input(
        "DataHub token",
        value=st.session_state.get("datahub_token", ""),
        type="password",
        help="Personal access token used as Bearer auth",
    )
    api_key = st.text_input(
        "Google API key (Gemini)",
        value=st.session_state.get("google_api_key", ""),
        type="password",
        help="Optional — deterministic fallback artifacts work without Gemini",
    )
    allow_wb = st.checkbox(
        "Enable DataHub write-back (disabled by default)",
        value=bool(st.session_state.get("allow_writeback", False)),
    )
    demo = st.checkbox("Demo mode (offline fixtures, no live MCP)", value=False)

    if st.button("Validate connection", type="primary"):
        st.session_state.datahub_mcp_url = mcp_url
        st.session_state.datahub_token = token
        st.session_state.google_api_key = api_key
        st.session_state.allow_writeback = allow_wb
        st.session_state.demo_mode = demo
        if demo:
            st.session_state.connected = True
            st.session_state.step = 1
            st.success("Demo mode ready")
            st.rerun()
        try:
            settings = _settings_from_session()
            if not settings.datahub_mcp_url.strip() or not settings.datahub_token.strip():
                raise ValueError("DATAHUB_MCP_URL and DATAHUB_TOKEN are required")
            tools = SessionTools(settings)
            client = DataHubClient(tools, settings)
            ok = _run(client.validate_connection())
            if not ok:
                raise DataHubError("Connection validation returned empty result")
            st.session_state.connected = True
            st.session_state.step = 1
            st.success("Connected to DataHub MCP")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Connection failed: {exc}")


def _step_select() -> None:
    st.subheader("Select asset")
    if not st.session_state.get("connected"):
        st.warning("Connect first")
        if st.button("Back"):
            st.session_state.step = 0
            st.rerun()
        return

    query = st.text_input("Search DataHub assets", value="orders")
    if st.session_state.get("demo_mode"):
        results = [
            {
                "urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)",
                "name": "ecommerce.public.orders",
            },
            {
                "urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.customers,PROD)",
                "name": "ecommerce.public.customers",
            },
        ]
    else:
        results = []
        if st.button("Search"):
            try:
                settings = _settings_from_session()
                tools = SessionTools(settings)
                client = DataHubClient(tools, settings)
                results = _run(client.search_assets(query))
                st.session_state.search_results = results
            except Exception as exc:  # noqa: BLE001
                st.error(f"Search failed: {exc}")
        results = st.session_state.get("search_results", results)

    labels = [f"{r['name']} — {r['urn']}" for r in results] or ["(no results yet)"]
    choice = st.selectbox("Asset", labels)
    manual = st.text_input("Or paste asset URN", value="")
    c1, c2 = st.columns(2)
    if c1.button("Back"):
        st.session_state.step = 0
        st.rerun()
    if c2.button("Continue", type="primary"):
        if manual.strip():
            st.session_state.asset_urn = manual.strip()
        elif results and choice in labels and results:
            st.session_state.asset_urn = results[labels.index(choice)]["urn"]
        else:
            st.error("Select or paste an asset URN")
            return
        st.session_state.step = 2
        st.rerun()


def _step_analyze() -> None:
    st.subheader("Analyze change")
    urn = st.session_state.get("asset_urn", "")
    st.markdown(f"**Asset:** `{urn}`")
    raw = st.text_area(
        "Describe the proposed change",
        placeholder="Example: DROP COLUMN customer_email  /  rename column amount to amount_usd",
        height=120,
    )
    uploaded = st.file_uploader("Optional SQL / dbt / schema.yml upload", type=["sql", "yml", "yaml", "txt"])
    sql_before = st.text_area("SQL before (for model replacement)", height=100)
    sql_after = st.text_area("SQL after (for model replacement)", height=100)
    uploaded_text = uploaded.read().decode("utf-8") if uploaded else None

    c1, c2 = st.columns(2)
    if c1.button("Back"):
        st.session_state.step = 1
        st.rerun()
    if c2.button("Run analysis", type="primary"):
        with st.spinner("Collecting DataHub evidence and scoring risk…"):
            try:
                if st.session_state.get("demo_mode"):
                    result = _run(_demo_analyze(urn, raw, sql_before, sql_after, uploaded_text))
                else:
                    settings = _settings_from_session()
                    tools = SessionTools(settings)
                    client = DataHubClient(tools, settings)
                    orch = AnalysisOrchestrator(client, settings)
                    result = _run(
                        orch.analyze(
                            asset_urn=urn,
                            raw_input=raw,
                            sql_before=sql_before or None,
                            sql_after=sql_after or None,
                            uploaded_text=uploaded_text,
                        )
                    )
                st.session_state.analysis = result
                st.session_state.step = 3
                st.rerun()
            except UnsupportedChangeError as exc:
                st.error(f"Unsupported change: {exc}")
            except (DataHubError, AgentError, StaleRunError) as exc:
                st.error(str(exc))
            except Exception as exc:  # noqa: BLE001
                st.error(f"Analysis failed: {exc}")


def _step_review() -> None:
    st.subheader("Review / export")
    result = st.session_state.get("analysis")
    if result is None:
        st.warning("No analysis yet")
        if st.button("Back"):
            st.session_state.step = 2
            st.rerun()
        return

    risk = result.risk
    cert = result.certificate or {}
    summary = cert.get("summary") or {}
    merge_allowed = cert.get("merge_allowed", True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Risk", f"{risk.level.value.upper()} ({risk.score})")
    c2.metric("BREAKS", summary.get("breaks", "—"))
    c3.metric("SAFE", summary.get("safe", "—"))
    c4.metric("Merge allowed", "YES" if merge_allowed else "NO")

    if not merge_allowed:
        st.error(
            "Breakage Certificate blocks merge: known DataHub queries will break. "
            "Apply consumer patches or use an explicit override in CI."
        )
    else:
        st.success("Breakage Certificate allows merge (no BREAKS).")

    st.write("**Why this is not just Impact Analysis**")
    st.caption(
        "DataHub lists dependents. ContextGuard proves which known queries break, "
        "emits patches, and gates merge on the certificate."
    )

    st.write("**Risk reasons**")
    for reason in risk.reasons:
        st.write(f"- {reason}")

    if result.evidence.unknowns:
        st.warning("Unknowns: " + "; ".join(result.evidence.unknowns))

    tabs = st.tabs(
        [
            "Certificate",
            "Consumer patches",
            "Report",
            "Compat SQL",
            "dbt tests",
            "Checklist",
            "Owner messages",
        ]
    )
    tabs[0].markdown(result.artifacts.certificate_md or "_No certificate_")
    tabs[1].code(result.artifacts.consumer_patches_sql or "-- none", language="sql")
    tabs[2].markdown(result.artifacts.impact_report_md)
    tabs[3].code(result.artifacts.compatibility_sql, language="sql")
    tabs[4].code(result.artifacts.dbt_tests_yml, language="yaml")
    tabs[5].markdown(result.artifacts.migration_checklist_md)
    tabs[6].write("\n\n".join(result.artifacts.owner_messages))

    zip_bytes = package_artifacts_zip(result)
    st.download_button(
        "Download artifacts ZIP",
        data=zip_bytes,
        file_name=f"contextguard-{result.run_id[:8]}.zip",
        mime="application/zip",
        type="primary",
    )

    settings = _settings_from_session()
    if settings.allow_writeback and not st.session_state.get("demo_mode"):
        st.divider()
        st.write("Write-back is explicit and separate from analysis.")
        if st.checkbox("I confirm saving this review document + tag to DataHub"):
            if st.button("Save review to DataHub"):
                try:
                    tools = SessionTools(settings)
                    client = DataHubClient(tools, settings)
                    orch = AnalysisOrchestrator(client, settings)
                    orch._latest_run_id = result.run_id
                    updated = _run(orch.writeback(result))
                    st.session_state.analysis = updated
                    st.success(f"Saved: {updated.writeback_document_urn}")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Write-back failed: {exc}")
    else:
        st.info("Write-back disabled (demo mode or CONTEXTGUARD_ALLOW_WRITEBACK=false).")

    if st.button("Analyze another change"):
        st.session_state.step = 2
        st.session_state.analysis = None
        st.rerun()


async def _demo_analyze(urn, raw, sql_before, sql_after, uploaded_text):
    from contextguard.cli import build_offline_result
    from contextguard.models import (
        ColumnRef,
        DownstreamAsset,
        EvidenceBundle,
        OwnerRef,
        QuerySnippet,
    )

    asset = (
        urn
        or "urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)"
    )
    evidence = EvidenceBundle(
        asset_urn=asset,
        asset_name="ecommerce.public.orders",
        schema_fields=[
            ColumnRef(urn=f"{asset}.id", name="id", native_type="NUMBER"),
            ColumnRef(urn=f"{asset}.amount", name="amount", native_type="NUMBER"),
            ColumnRef(
                urn=f"{asset}.customer_email",
                name="customer_email",
                native_type="VARCHAR",
            ),
            ColumnRef(urn=f"{asset}.status", name="status", native_type="VARCHAR"),
        ],
        downstream=[
            DownstreamAsset(
                urn="urn:li:dashboard:(looker,revenue_overview)",
                name="Revenue Overview",
                entity_type="dashboard",
                is_critical=True,
                column="amount",
            ),
            DownstreamAsset(
                urn="urn:li:dataset:(urn:li:dataPlatform:dbt,mart.order_metrics,PROD)",
                name="mart.order_metrics",
                column="amount",
            ),
        ],
        owners=[
            OwnerRef(
                urn="urn:li:corpuser:data-platform",
                name="Data Platform",
                email="dp@example.com",
            )
        ],
        queries=[
            QuerySnippet(query="select amount, customer_email from ecommerce.public.orders"),
            QuerySnippet(query="select id, status from ecommerce.public.orders"),
        ],
        quality_issues=["Freshness assertion delayed 2h"],
        unknowns=[],
    )
    return build_offline_result(
        raw or "drop column amount",
        evidence,
        sql_before=sql_before or None,
        sql_after=sql_after or None,
    )


if __name__ == "__main__":
    main()
