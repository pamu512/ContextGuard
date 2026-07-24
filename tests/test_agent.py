"""Tests for agent orchestration and artifact packaging."""

import json

import pytest

from contextguard.agent import AnalysisOrchestrator, StaleRunError, _extract_json
from contextguard.artifacts import (
    build_fallback_artifacts,
    package_artifacts_zip,
    validate_sql_against_schema,
    write_example_bundle,
)
from contextguard.config import Settings
from contextguard.datahub import DataHubClient
from contextguard.models import (
    ChangeType,
    ColumnRef,
    DownstreamAsset,
    EvidenceBundle,
    OwnerRef,
    ProposedChange,
    RiskLevel,
)


class FakeTools:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        urn = arguments.get("urn") or (arguments.get("urns") or [None])[0]
        if name == "get_entities":
            return {
                "name": "orders",
                "owners": [{"owner": "urn:li:corpuser:bob", "name": "Bob", "email": "b@x.com"}],
            }
        if name == "list_schema_fields":
            return [
                {"fieldPath": "amount", "nativeDataType": "NUMBER", "urn": f"{urn}.amount"},
                {"fieldPath": "id", "nativeDataType": "NUMBER", "urn": f"{urn}.id"},
            ]
        if name == "get_lineage":
            return [
                {
                    "urn": "urn:li:dashboard:rev",
                    "name": "Revenue",
                    "tags": ["critical"],
                    "column": "amount",
                }
            ]
        if name == "get_dataset_queries":
            return [{"query": "select amount from orders"}]
        if name == "save_document":
            return {"urn": "urn:li:document:cg-1"}
        if name == "add_tags":
            return {"ok": True}
        raise RuntimeError(name)


URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,db.public.orders,PROD)"


@pytest.fixture
def settings():
    return Settings(
        GOOGLE_API_KEY="",
        DATAHUB_MCP_URL="https://example.acryl.io/integrations/ai/mcp",
        DATAHUB_TOKEN="tok",
        CONTEXTGUARD_ALLOW_WRITEBACK=True,
    )


@pytest.mark.asyncio
async def test_analyze_uses_deterministic_fallback_without_llm(settings, tmp_path):
    client = DataHubClient(FakeTools(), settings)
    orch = AnalysisOrchestrator(client, settings, llm=None)
    result = await orch.analyze(asset_urn=URN, raw_input="drop column amount")
    assert result.change.change_type == ChangeType.DROP_COLUMN
    assert result.risk.level in {RiskLevel.HIGH, RiskLevel.CRITICAL, RiskLevel.MEDIUM}
    assert result.artifacts.impact_claims
    assert all(c.evidence_urns for c in result.artifacts.impact_claims)
    assert "CREATE OR REPLACE VIEW" in result.artifacts.compatibility_sql
    zipped = package_artifacts_zip(result)
    assert zipped.startswith(b"PK")
    write_example_bundle(result, tmp_path / "breaking")
    assert (tmp_path / "breaking" / "impact_report.md").exists()
    meta = json.loads((tmp_path / "breaking" / "result.json").read_text())
    assert meta["evidence"]["raw_tool_payloads"] == {}


@pytest.mark.asyncio
async def test_llm_invalid_then_repair(settings):
    client = DataHubClient(FakeTools(), settings)
    calls = {"n": 0}

    async def flaky_llm(_prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "not json"
        return json.dumps(
            {
                "impact_report_md": "# ok",
                "compatibility_sql": "SELECT id FROM orders",
                "dbt_tests_yml": "version: 2",
                "migration_checklist_md": "# list",
                "owner_messages": ["hi"],
                "impact_claims": [
                    {"claim": "Revenue may break", "evidence_urns": ["urn:li:dashboard:rev"]}
                ],
            }
        )

    orch = AnalysisOrchestrator(client, settings, llm=flaky_llm)
    # Force LLM path even without API key
    orch._settings = settings.model_copy(update={"google_api_key": "x"})
    result = await orch.analyze(asset_urn=URN, raw_input="drop column amount")
    assert result.artifacts.impact_report_md.startswith("# ok")
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_stale_run_guard(settings):
    client = DataHubClient(FakeTools(), settings)
    orch = AnalysisOrchestrator(client, settings)
    first = await orch.analyze(asset_urn=URN, raw_input="drop column amount", run_id="run-1")
    await orch.analyze(asset_urn=URN, raw_input="rename column amount to total", run_id="run-2")
    with pytest.raises(StaleRunError):
        await orch.writeback(first)


def test_extract_json_fenced():
    data = _extract_json('```json\n{"a": 1}\n```')
    assert data == {"a": 1}


def test_validate_sql_unknown_columns():
    evidence = EvidenceBundle(
        asset_urn=URN,
        asset_name="orders",
        schema_fields=[ColumnRef(urn=f"{URN}.id", name="id")],
    )
    warnings = validate_sql_against_schema("SELECT ghost FROM orders", evidence)
    assert any("ghost" in w for w in warnings)


def test_fallback_artifacts_for_rename():
    change = ProposedChange(
        change_type=ChangeType.RENAME_COLUMN,
        asset_urn=URN,
        column="amount",
        new_column="total",
    )
    evidence = EvidenceBundle(
        asset_urn=URN,
        asset_name="orders",
        schema_fields=[ColumnRef(urn=f"{URN}.amount", name="amount")],
        downstream=[
            DownstreamAsset(urn="urn:li:dashboard:x", name="X", column="amount"),
        ],
        owners=[OwnerRef(urn="urn:li:corpuser:a", name="A")],
    )
    from contextguard.analysis import score_risk

    risk = score_risk(change, evidence)
    arts = build_fallback_artifacts(change, evidence, risk)
    assert "total" in arts.compatibility_sql
    assert arts.owner_messages
