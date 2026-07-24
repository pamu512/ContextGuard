"""DataHub MCP client boundary — read tools for analysis, isolated write path."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Awaitable, Callable, Protocol

from contextguard.config import Settings, get_settings
from contextguard.models import (
    ColumnRef,
    DownstreamAsset,
    EvidenceBundle,
    OwnerRef,
    QuerySnippet,
)

logger = logging.getLogger(__name__)

READ_TOOLS = (
    "search",
    "get_entities",
    "get_lineage",
    "list_schema_fields",
    "get_dataset_queries",
)

WRITE_TOOLS = (
    "save_document",
    "add_tags",
)

_SECRET_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+|([A-Za-z0-9]{24,})", re.I)


class DataHubError(RuntimeError):
    """Sanitized DataHub / MCP failure."""


class ToolCaller(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


def sanitize_error(message: str) -> str:
    cleaned = _SECRET_RE.sub(r"\1***", message)
    return cleaned[:500]


async def _retry(
    fn: Callable[[], Awaitable[Any]],
    *,
    retries: int,
    timeout: float,
) -> Any:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(fn(), timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — boundary: sanitize then raise
            last = exc
            if attempt >= retries:
                break
            await asyncio.sleep(0.4 * (attempt + 1))
    raise DataHubError(sanitize_error(str(last) if last else "unknown MCP error"))


class DataHubClient:
    """Thin wrapper around MCP tool calls with read/write separation."""

    def __init__(
        self,
        tool_caller: ToolCaller,
        settings: Settings | None = None,
    ) -> None:
        self._tools = tool_caller
        self._settings = settings or get_settings()
        self._closed = False

    async def validate_connection(self) -> bool:
        result = await self._call_read("search", {"query": "*", "count": 1})
        return result is not None

    async def collect_evidence(self, asset_urn: str, query_hint: str = "") -> EvidenceBundle:
        entity = await self._call_read("get_entities", {"urns": [asset_urn]})
        fields_raw = await self._call_read("list_schema_fields", {"urn": asset_urn})
        lineage_raw = await self._call_read(
            "get_lineage",
            {"urn": asset_urn, "direction": "DOWNSTREAM", "max_hops": 2},
        )
        queries_raw = await self._call_read("get_dataset_queries", {"urn": asset_urn})

        name = _extract_name(entity, asset_urn)
        fields = _parse_fields(fields_raw, asset_urn)
        downstream = _parse_downstream(lineage_raw)
        owners = _parse_owners(entity)
        queries = _parse_queries(queries_raw)
        quality = _parse_quality(entity)
        unknowns: list[str] = []
        if not fields:
            unknowns.append("Schema fields unavailable from DataHub")
        if lineage_raw in (None, {}, []):
            unknowns.append("Downstream lineage unavailable from DataHub")

        return EvidenceBundle(
            asset_urn=asset_urn,
            asset_name=name,
            schema_fields=fields,
            downstream=downstream,
            owners=owners,
            queries=queries,
            quality_issues=quality,
            unknowns=unknowns,
            raw_tool_payloads={
                "entity": _safe_payload(entity),
                "fields": _safe_payload(fields_raw),
                "lineage": _safe_payload(lineage_raw),
                "queries": _safe_payload(queries_raw),
                "query_hint": query_hint,
            },
        )

    async def search_assets(self, query: str, count: int = 10) -> list[dict[str, str]]:
        raw = await self._call_read("search", {"query": query, "count": count})
        return _parse_search(raw)

    async def save_review_document(
        self,
        title: str,
        content: str,
        *,
        related_urn: str,
        tag: str = "contextguard-reviewed",
    ) -> dict[str, Any]:
        if not self._settings.allow_writeback:
            raise DataHubError("Write-back disabled (CONTEXTGUARD_ALLOW_WRITEBACK=false)")
        doc = await self._call_write(
            "save_document",
            {
                "title": title,
                "content": content,
                "related_urns": [related_urn],
            },
        )
        try:
            await self._call_write(
                "add_tags",
                {"urn": related_urn, "tags": [tag]},
            )
        except DataHubError as exc:
            logger.warning("Tag write failed after document save: %s", sanitize_error(str(exc)))
        return {"document": _safe_payload(doc), "tag": tag, "related_urn": related_urn}

    async def _call_read(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in READ_TOOLS:
            raise DataHubError(f"Tool `{name}` is not allowed on the read path")
        return await self._invoke(name, arguments)

    async def _call_write(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in WRITE_TOOLS:
            raise DataHubError(f"Tool `{name}` is not allowed on the write path")
        return await self._invoke(name, arguments)

    async def _invoke(self, name: str, arguments: dict[str, Any]) -> Any:
        async def _run() -> Any:
            return await self._tools.call_tool(name, arguments)

        return await _retry(
            _run,
            retries=self._settings.mcp_max_retries,
            timeout=self._settings.mcp_timeout_seconds,
        )


class AdkMcpToolCaller:
    """Adapter around Google ADK McpToolset."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._toolset = None
        self._tools_by_name: dict[str, Any] = {}

    async def connect(self) -> None:
        from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
        from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

        self._settings.require_datahub()
        self._toolset = McpToolset(
            connection_params=StreamableHTTPConnectionParams(
                url=self._settings.datahub_mcp_url.rstrip("/"),
                headers={"Authorization": f"Bearer {self._settings.datahub_token}"},
            ),
            tool_filter=list(READ_TOOLS + WRITE_TOOLS),
        )
        tools = await self._toolset.get_tools()
        self._tools_by_name = {t.name: t for t in tools}

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if not self._tools_by_name:
            await self.connect()
        tool = self._tools_by_name.get(name)
        if tool is None:
            raise DataHubError(f"MCP tool `{name}` not available")
        # ADK tool interfaces vary; support both run_async and call
        if hasattr(tool, "run_async"):
            return await tool.run_async(args=arguments, tool_context=None)
        if hasattr(tool, "call"):
            result = tool.call(**arguments)
            if asyncio.iscoroutine(result):
                return await result
            return result
        raise DataHubError(f"Unsupported MCP tool interface for `{name}`")

    async def close(self) -> None:
        if self._toolset is not None and hasattr(self._toolset, "close"):
            await self._toolset.close()
        self._toolset = None
        self._tools_by_name = {}


def _safe_payload(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("entities", "results", "fields", "schemaFields", "queries", "children"):
            if key in value and isinstance(value[key], list):
                return value[key]
        return [value]
    return [value]


def _extract_name(entity: Any, fallback: str) -> str:
    for item in _as_list(entity):
        if isinstance(item, dict):
            for key in ("name", "displayName", "properties"):
                val = item.get(key)
                if isinstance(val, str) and val:
                    return val
                if isinstance(val, dict) and val.get("name"):
                    return str(val["name"])
    return fallback.rsplit(",", 1)[0].rsplit(".", 1)[-1] if "," in fallback else fallback


def _parse_fields(raw: Any, asset_urn: str) -> list[ColumnRef]:
    out: list[ColumnRef] = []
    for item in _as_list(raw):
        if not isinstance(item, dict):
            continue
        name = item.get("fieldPath") or item.get("name") or item.get("field")
        if not name:
            continue
        out.append(
            ColumnRef(
                urn=str(item.get("urn") or f"{asset_urn}.{name}"),
                name=str(name),
                native_type=item.get("nativeDataType") or item.get("type"),
            )
        )
    return out


def _parse_downstream(raw: Any) -> list[DownstreamAsset]:
    out: list[DownstreamAsset] = []
    for item in _as_list(raw):
        if not isinstance(item, dict):
            continue
        urn = item.get("urn") or item.get("entity") or item.get("entityUrn")
        if not urn:
            continue
        name = str(item.get("name") or item.get("displayName") or urn)
        tags = item.get("tags") or []
        critical = any(
            str(t).lower() in {"critical", "pii", "tier1", "gold"} for t in _as_list(tags)
        ) or bool(item.get("is_critical"))
        out.append(
            DownstreamAsset(
                urn=str(urn),
                name=name,
                entity_type=str(item.get("type") or item.get("entityType") or "dataset"),
                is_critical=critical,
                column=item.get("column") or item.get("fieldPath"),
            )
        )
    return out


def _parse_owners(entity: Any) -> list[OwnerRef]:
    out: list[OwnerRef] = []
    for item in _as_list(entity):
        if not isinstance(item, dict):
            continue
        owners = item.get("owners") or item.get("ownership") or []
        if isinstance(owners, dict):
            owners = owners.get("owners", [])
        for owner in _as_list(owners):
            if not isinstance(owner, dict):
                continue
            urn = owner.get("owner") or owner.get("urn") or owner.get("ownerUrn")
            if not urn:
                continue
            out.append(
                OwnerRef(
                    urn=str(urn),
                    name=str(owner.get("name") or urn),
                    email=owner.get("email"),
                )
            )
    return out


def _parse_queries(raw: Any) -> list[QuerySnippet]:
    out: list[QuerySnippet] = []
    for item in _as_list(raw):
        if isinstance(item, str):
            out.append(QuerySnippet(query=item))
            continue
        if not isinstance(item, dict):
            continue
        q = item.get("query") or item.get("sql") or item.get("statement")
        if q:
            out.append(QuerySnippet(query=str(q), source=item.get("source")))
    return out


def _parse_quality(entity: Any) -> list[str]:
    issues: list[str] = []
    for item in _as_list(entity):
        if not isinstance(item, dict):
            continue
        for key in ("qualityIssues", "assertions", "incidents"):
            for q in _as_list(item.get(key)):
                if isinstance(q, str):
                    issues.append(q)
                elif isinstance(q, dict):
                    msg = q.get("message") or q.get("type") or q.get("name")
                    if msg:
                        issues.append(str(msg))
    return issues


def _parse_search(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in _as_list(raw):
        if not isinstance(item, dict):
            continue
        urn = item.get("urn") or item.get("entityUrn")
        if not urn:
            continue
        out.append(
            {
                "urn": str(urn),
                "name": str(item.get("name") or item.get("displayName") or urn),
            }
        )
    return out
