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
_QUALIFIED = re.compile(
    r"(?P<table>[A-Za-z_][\w]*)\.(?P<col>[A-Za-z_][\w]*)"
)
_QUOTED = re.compile(r'[`"\[]([A-Za-z_][\w]*)[`"\]]')
_SELECT_STAR = re.compile(r"(?is)\bselect\s+(?:distinct\s+)?\*")

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
    "except",
    "exclude",
}


def extract_identifiers(sql: str) -> set[str]:
    """Bare + quoted identifiers (not table.col table parts)."""
    found = {m.group(0).lower() for m in _IDENT.finditer(sql)} - _SQL_KEYWORDS
    found |= {m.group(1).lower() for m in _QUOTED.finditer(sql)}
    # Prefer column side of qualified names
    for m in _QUALIFIED.finditer(sql):
        found.add(m.group("col").lower())
        found.discard(m.group("table").lower())
    return found


def references_column(sql: str, column: str) -> bool:
    """True if SQL references column bare, quoted, or qualified (t.col)."""
    col = column.lower()
    if re.search(rf"(?i)(?<![A-Za-z0-9_]){re.escape(col)}(?![A-Za-z0-9_])", sql):
        return True
    if re.search(rf'(?i)[`"\[]{re.escape(col)}[`"\]]', sql):
        return True
    if re.search(rf"(?i)\b[A-Za-z_][\w]*\.{re.escape(col)}\b", sql):
        return True
    return False


def has_select_star(sql: str) -> bool:
    return bool(_SELECT_STAR.search(sql))


def asset_name_tokens(evidence: EvidenceBundle) -> set[str]:
    name = evidence.asset_name.lower()
    parts = {p for p in re.split(r"[.\s]+", name) if p}
    # also last segment of URN path-ish
    if "," in evidence.asset_urn:
        mid = evidence.asset_urn.split(",")[1] if evidence.asset_urn.count(",") >= 1 else ""
        parts |= {p for p in re.split(r"[.\s]+", mid.lower()) if p and p != "prod"}
    return parts


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
    referenced = sorted(
        {c for c in schema_cols if references_column(sql, c)}
        if schema_cols
        else idents
    )
    col = (change.column or "").lower() or None
    new_col = (change.new_column or "").lower() or None
    star = has_select_star(sql)
    touches_asset = bool(idents & asset_name_tokens(evidence)) or bool(
        referenced
    )

    if change.change_type == ChangeType.DROP_COLUMN:
        if not col:
            return _unknown(sql, snippet, evidence_urns, referenced, "Drop change missing column name")
        if references_column(sql, col):
            return QueryImpact(
                query=sql,
                source=snippet.source,
                verdict=QueryVerdict.BREAKS,
                reason=f"Query references dropped column `{change.column}`",
                evidence_urns=evidence_urns,
                referenced_columns=referenced,
                suggested_patch=_patch_drop(sql, change.column or col),
            )
        if star and touches_asset:
            return QueryImpact(
                query=sql,
                source=snippet.source,
                verdict=QueryVerdict.BREAKS,
                reason=(
                    f"Query uses SELECT * against `{evidence.asset_name}` — "
                    f"dropping `{change.column}` changes the projection"
                ),
                evidence_urns=evidence_urns,
                referenced_columns=referenced,
                suggested_patch=(
                    f"-- Replace SELECT * with an explicit column list excluding `{change.column}`\n"
                    f"-- Suggested columns: "
                    + ", ".join(sorted(schema_cols - {col}) or ["<explicit columns>"])
                    + f"\n{sql}\n"
                ),
            )
        if star and not touches_asset:
            return _unknown(
                sql,
                snippet,
                evidence_urns,
                referenced,
                "SELECT * present but could not prove it targets this asset",
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
            return _unknown(
                sql, snippet, evidence_urns, referenced, "Rename change missing old/new column"
            )
        if references_column(sql, col):
            patch = re.sub(
                rf"(?i)\b{re.escape(change.column or col)}\b",
                change.new_column or new_col,
                sql,
            )
            patch = re.sub(
                rf"(?i)([A-Za-z_][\w]*)\.{re.escape(change.column or col)}\b",
                rf"\1.{change.new_column or new_col}",
                patch,
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
        if star and touches_asset:
            return QueryImpact(
                query=sql,
                source=snippet.source,
                verdict=QueryVerdict.BREAKS,
                reason=(
                    f"SELECT * against `{evidence.asset_name}` will expose "
                    f"`{change.new_column}` instead of `{change.column}`"
                ),
                evidence_urns=evidence_urns,
                referenced_columns=referenced,
                suggested_patch=(
                    f"-- Explicitly select `{change.new_column}` "
                    f"(formerly `{change.column}`)\n{sql}\n"
                ),
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
            return _unknown(
                sql, snippet, evidence_urns, referenced, "Type change missing column name"
            )
        if not references_column(sql, col):
            if star and touches_asset:
                return _unknown(
                    sql,
                    snippet,
                    evidence_urns,
                    referenced,
                    f"SELECT * may include `{change.column}` type change — not proven",
                )
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
        if _type_change_risky(old_t, new_t):
            patched = re.sub(
                rf"(?i)\b{re.escape(change.column or col)}\b",
                f"CAST({change.column} AS {change.new_type or 'VARCHAR'})",
                sql,
                count=1,
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
                suggested_patch=(
                    f"-- Cast for type migration {change.old_type} -> {change.new_type}\n"
                    f"{patched}\n"
                ),
            )
        return _unknown(
            sql,
            snippet,
            evidence_urns,
            referenced,
            "Type change impact on this query could not be proven from metadata",
        )

    before_idents = extract_identifiers(change.sql_before or "")
    after_idents = extract_identifiers(change.sql_after or "")
    removed = before_idents - after_idents
    if not change.sql_before or not change.sql_after:
        return _unknown(
            sql,
            snippet,
            evidence_urns,
            referenced,
            "Model SQL replacement missing before/after for query proof",
        )
    hit = sorted({c for c in removed if references_column(sql, c)})
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
                f"{sql}\n"
            ),
        )
    if not (idents & (before_idents | after_idents | schema_cols)):
        return _unknown(
            sql,
            snippet,
            evidence_urns,
            referenced,
            "Could not prove whether query depends on rewritten model columns",
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


def _unknown(sql, snippet, evidence_urns, referenced, reason: str) -> QueryImpact:
    return QueryImpact(
        query=sql,
        source=snippet.source,
        verdict=QueryVerdict.UNKNOWN,
        reason=reason,
        evidence_urns=evidence_urns,
        referenced_columns=referenced,
    )


def _patch_drop(sql: str, column: str) -> str:
    patched = re.sub(
        rf"(?i)([A-Za-z_][\w]*)\.{re.escape(column)}\b",
        r"\1./*REMOVED*/NULL",
        sql,
    )
    patched = re.sub(
        rf"(?i)(?<![A-Za-z0-9_.]){re.escape(column)}(?![A-Za-z0-9_])",
        f"/* REMOVED:{column} */ NULL",
        patched,
    )
    return (
        f"-- Consumer patch: stop selecting dropped column `{column}`\n"
        f"{patched}\n"
    )


def _type_change_risky(old_t: str, new_t: str) -> bool:
    if not new_t or not old_t:
        return True
    numeric = {"number", "int", "integer", "bigint", "float", "double", "decimal", "numeric"}
    stringy = {"varchar", "string", "text", "char"}
    old_n = any(x in old_t for x in numeric)
    new_n = any(x in new_t for x in numeric)
    old_s = any(x in old_t for x in stringy)
    new_s = any(x in new_t for x in stringy)
    if (old_n and new_s) or (old_s and new_n):
        return True
    return old_t != new_t
