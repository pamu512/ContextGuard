"""Deterministic classification of known DataHub queries vs a proposed change."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field

from contextguard.models import ChangeType, EvidenceBundle, ProposedChange, QuerySnippet


class QueryVerdict(str, Enum):
    BREAKS = "BREAKS"
    SAFE = "SAFE"
    UNKNOWN = "UNKNOWN"


class QueryImpact(BaseModel):
    query: str
    source: str | None = None
    verdict: QueryVerdict
    reason: str
    evidence_urns: list[str] = Field(default_factory=list)
    referenced_columns: list[str] = Field(default_factory=list)
    suggested_patch: str | None = None


_IDENT = re.compile(r"[A-Za-z_][\w]*")
_SQL_KEYWORDS = {
    "select",
    "from",
    "where",
    "and",
    "or",
    "as",
    "join",
    "left",
    "right",
    "inner",
    "outer",
    "on",
    "group",
    "by",
    "order",
    "limit",
    "with",
    "case",
    "when",
    "then",
    "else",
    "end",
    "null",
    "is",
    "not",
    "in",
    "between",
    "like",
    "distinct",
    "count",
    "sum",
    "avg",
    "min",
    "max",
    "cast",
    "coalesce",
    "having",
    "union",
    "all",
    "true",
    "false",
    "over",
    "partition",
    "asc",
    "desc",
    "exists",
}


def extract_identifiers(sql: str) -> set[str]:
    return {m.group(0).lower() for m in _IDENT.finditer(sql)} - _SQL_KEYWORDS


def classify_query(
    snippet: QuerySnippet,
    change: ProposedChange,
    evidence: EvidenceBundle,
) -> QueryImpact:
    sql = (snippet.query or "").strip()
    evidence_urns = [evidence.asset_urn]
    if not sql:
        return QueryImpact(
            query=sql,
            source=snippet.source,
            verdict=QueryVerdict.UNKNOWN,
            reason="Empty query text from DataHub",
            evidence_urns=evidence_urns,
        )

    idents = extract_identifiers(sql)
    schema_cols = {f.name.lower() for f in evidence.schema_fields}
    referenced = sorted(idents & schema_cols) if schema_cols else sorted(idents)
    col = (change.column or "").lower() or None
    new_col = (change.new_column or "").lower() or None

    if change.change_type == ChangeType.DROP_COLUMN:
        if not col:
            return QueryImpact(
                query=sql,
                source=snippet.source,
                verdict=QueryVerdict.UNKNOWN,
                reason="Drop change missing column name",
                evidence_urns=evidence_urns,
                referenced_columns=referenced,
            )
        if col in idents:
            patch = _patch_drop(sql, change.column or col)
            return QueryImpact(
                query=sql,
                source=snippet.source,
                verdict=QueryVerdict.BREAKS,
                reason=f"Query references dropped column `{change.column}`",
                evidence_urns=evidence_urns,
                referenced_columns=referenced,
                suggested_patch=patch,
            )
        return QueryImpact(
            query=sql,
            source=snippet.source,
            verdict=QueryVerdict.SAFE,
            reason=f"Query does not reference `{change.column}`",
            evidence_urns=evidence_urns,
            referenced_columns=referenced,
        )

    if change.change_type == ChangeType.RENAME_COLUMN:
        if not col or not new_col:
            return QueryImpact(
                query=sql,
                source=snippet.source,
                verdict=QueryVerdict.UNKNOWN,
                reason="Rename change missing old/new column",
                evidence_urns=evidence_urns,
                referenced_columns=referenced,
            )
        if col in idents:
            patch = re.sub(
                rf"\b{re.escape(change.column or col)}\b",
                change.new_column or new_col,
                sql,
                flags=re.IGNORECASE,
            )
            return QueryImpact(
                query=sql,
                source=snippet.source,
                verdict=QueryVerdict.BREAKS,
                reason=f"Query references old column name `{change.column}`",
                evidence_urns=evidence_urns,
                referenced_columns=referenced,
                suggested_patch=patch,
            )
        return QueryImpact(
            query=sql,
            source=snippet.source,
            verdict=QueryVerdict.SAFE,
            reason=f"Query does not reference `{change.column}`",
            evidence_urns=evidence_urns,
            referenced_columns=referenced,
        )

    if change.change_type == ChangeType.TYPE_CHANGE:
        if not col:
            return QueryImpact(
                query=sql,
                source=snippet.source,
                verdict=QueryVerdict.UNKNOWN,
                reason="Type change missing column name",
                evidence_urns=evidence_urns,
                referenced_columns=referenced,
            )
        if col not in idents:
            return QueryImpact(
                query=sql,
                source=snippet.source,
                verdict=QueryVerdict.SAFE,
                reason=f"Query does not reference `{change.column}`",
                evidence_urns=evidence_urns,
                referenced_columns=referenced,
            )
        old_t = (change.old_type or "").lower()
        new_t = (change.new_type or "").lower()
        if old_t and new_t and old_t == new_t:
            return QueryImpact(
                query=sql,
                source=snippet.source,
                verdict=QueryVerdict.SAFE,
                reason="Type change is a no-op (same type)",
                evidence_urns=evidence_urns,
                referenced_columns=referenced,
            )
        # Narrowing / string↔number style changes are treated as breaking for consumers
        risky = _type_change_risky(old_t, new_t)
        if risky:
            patch = (
                f"-- Cast for type migration {change.old_type} -> {change.new_type}\n"
                + re.sub(
                    rf"\b{re.escape(change.column or col)}\b",
                    f"CAST({change.column} AS {change.new_type or 'VARCHAR'})",
                    sql,
                    count=1,
                    flags=re.IGNORECASE,
                )
            )
            return QueryImpact(
                query=sql,
                source=snippet.source,
                verdict=QueryVerdict.BREAKS,
                reason=(
                    f"Query references `{change.column}` undergoing type change "
                    f"{change.old_type or '?'} → {change.new_type or '?'}"
                ),
                evidence_urns=evidence_urns,
                referenced_columns=referenced,
                suggested_patch=patch,
            )
        return QueryImpact(
            query=sql,
            source=snippet.source,
            verdict=QueryVerdict.UNKNOWN,
            reason="Type change impact on this query could not be proven from metadata",
            evidence_urns=evidence_urns,
            referenced_columns=referenced,
        )

    # MODEL_SQL_REPLACEMENT — prove overlap with removed columns when possible
    before_idents = extract_identifiers(change.sql_before or "")
    after_idents = extract_identifiers(change.sql_after or "")
    removed = before_idents - after_idents
    if not change.sql_before or not change.sql_after:
        return QueryImpact(
            query=sql,
            source=snippet.source,
            verdict=QueryVerdict.UNKNOWN,
            reason="Model SQL replacement missing before/after for query proof",
            evidence_urns=evidence_urns,
            referenced_columns=referenced,
        )
    hit = sorted(idents & removed)
    if hit:
        return QueryImpact(
            query=sql,
            source=snippet.source,
            verdict=QueryVerdict.BREAKS,
            reason=f"Query uses columns removed by model rewrite: {', '.join(hit)}",
            evidence_urns=evidence_urns,
            referenced_columns=referenced,
            suggested_patch=(
                "-- Review consumer against new model SQL\n"
                f"-- Removed columns: {', '.join(hit)}\n"
                f"{sql}"
            ),
        )
    if not (idents & (before_idents | after_idents | schema_cols)):
        return QueryImpact(
            query=sql,
            source=snippet.source,
            verdict=QueryVerdict.UNKNOWN,
            reason="Could not prove whether query depends on rewritten model columns",
            evidence_urns=evidence_urns,
            referenced_columns=referenced,
        )
    return QueryImpact(
        query=sql,
        source=snippet.source,
        verdict=QueryVerdict.SAFE,
        reason="Query does not reference columns removed by model rewrite",
        evidence_urns=evidence_urns,
        referenced_columns=referenced,
    )


def classify_queries(
    change: ProposedChange,
    evidence: EvidenceBundle,
) -> list[QueryImpact]:
    if not evidence.queries:
        return [
            QueryImpact(
                query="",
                verdict=QueryVerdict.UNKNOWN,
                reason="No known queries returned by DataHub for this asset",
                evidence_urns=[evidence.asset_urn],
            )
        ]
    return [classify_query(q, change, evidence) for q in evidence.queries]


def _patch_drop(sql: str, column: str) -> str:
    # Best-effort: comment the column reference and suggest removal
    patched = re.sub(
        rf"\b{re.escape(column)}\b",
        f"/* REMOVED:{column} */ NULL",
        sql,
        flags=re.IGNORECASE,
    )
    return (
        f"-- Consumer patch: stop selecting dropped column `{column}`\n"
        f"{patched}\n"
    )


def _type_change_risky(old_t: str, new_t: str) -> bool:
    if not new_t:
        return True
    if not old_t:
        return True
    numeric = {"number", "int", "integer", "bigint", "float", "double", "decimal", "numeric"}
    stringy = {"varchar", "string", "text", "char"}
    old_n = any(x in old_t for x in numeric)
    new_n = any(x in new_t for x in numeric)
    old_s = any(x in old_t for x in stringy)
    new_s = any(x in new_t for x in stringy)
    if old_n and new_s:
        return True
    if old_s and new_n:
        return True
    if old_t != new_t:
        return True
    return False
