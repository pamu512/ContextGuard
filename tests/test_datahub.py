"""Mocked DataHub MCP contract tests."""

import pytest

from contextguard.config import Settings
from contextguard.datahub import DataHubClient, DataHubError, sanitize_error


class FakeTools:
    def __init__(self, responses=None, fail_times=0):
        self.responses = responses or {}
        self.calls = []
        self.fail_times = fail_times
        self._fails = 0

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self._fails < self.fail_times:
            self._fails += 1
            raise RuntimeError("transient Bearer secret-token-value-1234567890 failure")
        if name not in self.responses:
            raise RuntimeError(f"unexpected tool {name}")
        return self.responses[name]


URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,db.public.orders,PROD)"


@pytest.fixture
def settings():
    return Settings(
        GOOGLE_API_KEY="g",
        DATAHUB_MCP_URL="https://example.acryl.io/integrations/ai/mcp",
        DATAHUB_TOKEN="tok",
        CONTEXTGUARD_ALLOW_WRITEBACK=True,
        CONTEXTGUARD_MCP_TIMEOUT=5,
        CONTEXTGUARD_MCP_RETRIES=2,
    )


@pytest.mark.asyncio
async def test_collect_evidence_happy_path(settings):
    tools = FakeTools(
        {
            "get_entities": {
                "name": "orders",
                "owners": [{"owner": "urn:li:corpuser:alice", "name": "Alice"}],
                "qualityIssues": ["Freshness late"],
            },
            "list_schema_fields": [
                {"fieldPath": "amount", "nativeDataType": "NUMBER", "urn": f"{URN}.amount"}
            ],
            "get_lineage": [
                {
                    "urn": "urn:li:dashboard:revenue",
                    "name": "Revenue",
                    "type": "dashboard",
                    "tags": ["critical"],
                    "column": "amount",
                }
            ],
            "get_dataset_queries": [{"query": "select amount from orders"}],
        }
    )
    client = DataHubClient(tools, settings)
    evidence = await client.collect_evidence(URN)
    assert evidence.asset_name == "orders"
    assert evidence.schema_fields[0].name == "amount"
    assert evidence.downstream[0].is_critical
    assert evidence.owners[0].name == "Alice"
    assert evidence.queries[0].query.startswith("select")
    assert {"get_entities", "list_schema_fields", "get_lineage", "get_dataset_queries"} <= {
        c[0] for c in tools.calls
    }


@pytest.mark.asyncio
async def test_read_path_rejects_write_tool(settings):
    tools = FakeTools({})
    client = DataHubClient(tools, settings)
    with pytest.raises(DataHubError, match="not allowed on the read path"):
        await client._call_read("save_document", {"title": "x"})


@pytest.mark.asyncio
async def test_writeback_disabled_by_default():
    tools = FakeTools({})
    settings = Settings(
        GOOGLE_API_KEY="g",
        DATAHUB_MCP_URL="https://x/mcp",
        DATAHUB_TOKEN="t",
        CONTEXTGUARD_ALLOW_WRITEBACK=False,
    )
    client = DataHubClient(tools, settings)
    with pytest.raises(DataHubError, match="Write-back disabled"):
        await client.save_review_document("t", "c", related_urn=URN)


@pytest.mark.asyncio
async def test_writeback_idempotent_calls(settings):
    tools = FakeTools(
        {
            "save_document": {"urn": "urn:li:document:1"},
            "add_tags": {"ok": True},
        }
    )
    client = DataHubClient(tools, settings)
    first = await client.save_review_document("Review", "body", related_urn=URN)
    second = await client.save_review_document("Review", "body", related_urn=URN)
    assert first["document"]["urn"] == "urn:li:document:1"
    assert second["tag"] == "contextguard-reviewed"  # default tag on client API
    assert sum(1 for n, _ in tools.calls if n == "save_document") == 2


@pytest.mark.asyncio
async def test_retry_then_success(settings):
    tools = FakeTools(
        {
            "search": {"results": [{"urn": URN, "name": "orders"}]},
        },
        fail_times=1,
    )
    client = DataHubClient(tools, settings)
    ok = await client.validate_connection()
    assert ok
    assert len(tools.calls) == 2


def test_sanitize_error_redacts_secrets():
    msg = sanitize_error("Authorization Bearer secret-token-value-1234567890 failed")
    assert "secret-token-value" not in msg
    assert "***" in msg
