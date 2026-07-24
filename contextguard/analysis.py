"""Change parsers and deterministic risk scoring."""

from __future__ import annotations

import re
from typing import Iterable

from contextguard.models import (
    ChangeType,
    DownstreamAsset,
    EvidenceBundle,
    ProposedChange,
    RiskAssessment,
    RiskLevel,
)

_DROP = re.compile(
    r"(?i)\b(?:drop|remove|delete)\s+(?:the\s+)?(?:column\s+)?[`\"\[]?(?P<col>[A-Za-z_][\w]*)[`\"\]]?"
)
_RENAME = re.compile(
    r"(?i)\b(?:rename|renaming)\s+(?:column\s+)?[`\"\[]?(?P<old>[A-Za-z_][\w]*)[`\"\]]?"
    r"\s+(?:to|as|->)\s+[`\"\[]?(?P<new>[A-Za-z_][\w]*)[`\"\]]?"
)
_TYPE = re.compile(
    r"(?i)\b(?:change|alter|cast)\s+(?:column\s+)?[`\"\[]?(?P<col>[A-Za-z_][\w]*)[`\"\]]?"
    r".*?\b(?:from\s+)?(?P<old>[A-Za-z][\w()]+)\s+(?:to|->)\s+(?P<new>[A-Za-z][\w()]+)"
)
_SQL_REPLACEMENT = re.compile(r"(?is)\b(?:replace|rewrite|update)\s+(?:the\s+)?(?:dbt\s+)?model\b")
_ALTER_DROP = re.compile(
    r"(?i)alter\s+table\s+.+?\s+drop\s+column\s+[`\"\[]?(?P<col>[A-Za-z_][\w]*)[`\"\]]?"
)
_ALTER_RENAME = re.compile(
    r"(?i)alter\s+table\s+.+?\s+rename\s+column\s+[`\"\[]?(?P<old>[A-Za-z_][\w]*)[`\"\]]?"
    r"\s+to\s+[`\"\[]?(?P<new>[A-Za-z_][\w]*)[`\"\]]?"
)
_ALTER_TYPE = re.compile(
    r"(?i)alter\s+table\s+.+?\s+alter\s+column\s+[`\"\[]?(?P<col>[A-Za-z_][\w]*)[`\"\]]?"
    r"\s+(?:set\s+data\s+type|type)\s+(?P<new>[A-Za-z][\w()]+)"
)


class UnsupportedChangeError(ValueError):
    """Raised when input cannot be mapped to an MVP change type."""


def parse_proposed_change(
    raw_input: str,
    asset_urn: str,
    *,
    sql_before: str | None = None,
    sql_after: str | None = None,
    uploaded_text: str | None = None,
) -> ProposedChange:
    text = (raw_input or "").strip()
    blob = "\n".join(part for part in (text, uploaded_text or "") if part).strip()
    if not blob and not (sql_before and sql_after):
        raise UnsupportedChangeError("Empty change description")

    if sql_before is not None and sql_after is not None and sql_before.strip() != sql_after.strip():
        return ProposedChange(
            change_type=ChangeType.MODEL_SQL_REPLACEMENT,
            asset_urn=asset_urn,
            sql_before=sql_before,
            sql_after=sql_after,
            raw_input=blob or "model_sql_replacement",
        )

    if m := _ALTER_DROP.search(blob):
        return ProposedChange(
            change_type=ChangeType.DROP_COLUMN,
            asset_urn=asset_urn,
            column=m.group("col"),
            raw_input=blob,
        )
    if m := _ALTER_RENAME.search(blob):
        return ProposedChange(
            change_type=ChangeType.RENAME_COLUMN,
            asset_urn=asset_urn,
            column=m.group("old"),
            new_column=m.group("new"),
            raw_input=blob,
        )
    if m := _ALTER_TYPE.search(blob):
        return ProposedChange(
            change_type=ChangeType.TYPE_CHANGE,
            asset_urn=asset_urn,
            column=m.group("col"),
            new_type=m.group("new"),
            raw_input=blob,
        )
    if m := _RENAME.search(blob):
        return ProposedChange(
            change_type=ChangeType.RENAME_COLUMN,
            asset_urn=asset_urn,
            column=m.group("old"),
            new_column=m.group("new"),
            raw_input=blob,
        )
    if m := _TYPE.search(blob):
        return ProposedChange(
            change_type=ChangeType.TYPE_CHANGE,
            asset_urn=asset_urn,
            column=m.group("col"),
            old_type=m.group("old"),
            new_type=m.group("new"),
            raw_input=blob,
        )
    if m := _DROP.search(blob):
        return ProposedChange(
            change_type=ChangeType.DROP_COLUMN,
            asset_urn=asset_urn,
            column=m.group("col"),
            raw_input=blob,
        )
    if _SQL_REPLACEMENT.search(blob) or "select" in blob.lower():
        # Ambiguous model rewrite without before/after pair
        if sql_after:
            return ProposedChange(
                change_type=ChangeType.MODEL_SQL_REPLACEMENT,
                asset_urn=asset_urn,
                sql_before=sql_before,
                sql_after=sql_after,
                raw_input=blob,
            )
        raise UnsupportedChangeError(
            "Model SQL replacement requires sql_before and sql_after (or an uploaded pair)"
        )

    raise UnsupportedChangeError(
        "Unsupported change. MVP supports: drop column, rename column, type change, "
        "or dbt model SQL replacement."
    )


def column_exists(evidence: EvidenceBundle, column: str | None) -> bool:
    if not column:
        return False
    target = column.lower()
    return any(field.name.lower() == target for field in evidence.schema_fields)


def filter_downstream_for_column(
    downstream: Iterable[DownstreamAsset],
    column: str | None,
) -> list[DownstreamAsset]:
    if not column:
        return list(downstream)
    target = column.lower()
    matched = [d for d in downstream if d.column and d.column.lower() == target]
    # If lineage is table-level only, keep all downstream as potential impact
    return matched or list(downstream)


def score_risk(change: ProposedChange, evidence: EvidenceBundle) -> RiskAssessment:
    affected = filter_downstream_for_column(evidence.downstream, change.column)
    reasons: list[str] = []
    score = 0

    dep_count = len(affected)
    critical_count = sum(1 for a in affected if a.is_critical)
    owner_count = len(evidence.owners)
    query_count = len(evidence.queries)
    quality_count = len(evidence.quality_issues)

    if change.change_type == ChangeType.DROP_COLUMN:
        score += 35
        reasons.append("Dropping a column is a breaking schema change")
    elif change.change_type == ChangeType.RENAME_COLUMN:
        score += 30
        reasons.append("Renaming a column breaks consumers that reference the old name")
    elif change.change_type == ChangeType.TYPE_CHANGE:
        score += 25
        reasons.append("Type changes can break casts, joins, and BI calculations")
    elif change.change_type == ChangeType.MODEL_SQL_REPLACEMENT:
        score += 20
        reasons.append("Model SQL replacement can alter grain, filters, or column set")

    if change.column and not column_exists(evidence, change.column):
        score += 15
        reasons.append(f"Column `{change.column}` was not found in retrieved schema")
        evidence.unknowns.append(f"Column `{change.column}` missing from schema metadata")

    if dep_count:
        score += min(30, dep_count * 5)
        reasons.append(f"{dep_count} downstream asset(s) depend on this asset/column")
    else:
        reasons.append("No downstream dependencies found in DataHub lineage")

    if critical_count:
        score += min(20, critical_count * 10)
        reasons.append(f"{critical_count} critical downstream asset(s) affected")

    if query_count:
        score += min(10, query_count * 2)
        reasons.append(f"{query_count} known quer(ies) reference this asset")

    if owner_count == 0:
        score += 5
        reasons.append("No owners found — coordination risk is unknown")
        evidence.unknowns.append("Ownership metadata unavailable")
    else:
        reasons.append(f"{owner_count} owner(s) should be notified")

    if quality_count:
        score += min(10, quality_count * 3)
        reasons.append(f"{quality_count} existing quality issue(s) on this asset")

    score = max(0, min(100, score))
    level = _level_for_score(score)
    return RiskAssessment(
        level=level,
        score=score,
        reasons=reasons,
        affected_assets=affected,
        owner_count=owner_count,
        query_usage_count=query_count,
        quality_issue_count=quality_count,
    )


def _level_for_score(score: int) -> RiskLevel:
    if score >= 75:
        return RiskLevel.CRITICAL
    if score >= 50:
        return RiskLevel.HIGH
    if score >= 25:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW
