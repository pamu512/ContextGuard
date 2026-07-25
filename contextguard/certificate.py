"""Breakage Certificate (cgcert/v1) — the judge-facing differentiator."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from contextguard.models import ProposedChange, RiskAssessment
from contextguard.query_impact import QueryImpact, QueryVerdict


CERT_VERSION = "cgcert/v1"


class CertificateSummary(BaseModel):
    breaks: int = 0
    safe: int = 0
    unknown: int = 0


class BreakageCertificate(BaseModel):
    version: str = CERT_VERSION
    run_id: str
    issued_at: str
    asset_urn: str
    asset_name: str
    change: ProposedChange
    risk_level: str
    risk_score: int
    queries: list[QueryImpact] = Field(default_factory=list)
    summary: CertificateSummary = Field(default_factory=CertificateSummary)
    merge_allowed: bool = True
    content_hash: str = ""
    notes: list[str] = Field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"# ContextGuard Breakage Certificate (`{self.version}`)",
            "",
            f"- **Run:** `{self.run_id}`",
            f"- **Issued:** {self.issued_at}",
            f"- **Asset:** `{self.asset_name}` (`{self.asset_urn}`)",
            f"- **Change:** `{self.change.change_type.value}` "
            f"{self.change.column or ''} "
            f"{('→ ' + self.change.new_column) if self.change.new_column else ''}"
            f"{('→ ' + self.change.new_type) if self.change.new_type else ''}".strip(),
            f"- **Risk:** {self.risk_level.upper()} ({self.risk_score})",
            f"- **Merge allowed:** {'YES' if self.merge_allowed else 'NO'}",
            f"- **Hash:** `{self.content_hash}`",
            "",
            "## Summary",
            f"- BREAKS: **{self.summary.breaks}**",
            f"- SAFE: **{self.summary.safe}**",
            f"- UNKNOWN: **{self.summary.unknown}**",
            "",
            "## Query verdicts",
        ]
        if not self.queries:
            lines.append("_No queries classified._")
        for i, q in enumerate(self.queries, 1):
            preview = (q.query or "").replace("\n", " ")[:120]
            lines.append(f"### {i}. `{q.verdict.value}`")
            lines.append(f"- Query: `{preview}`")
            lines.append(f"- Reason: {q.reason}")
            lines.append(
                "- Evidence: " + ", ".join(f"`{u}`" for u in q.evidence_urns)
            )
            if q.suggested_patch:
                lines.append("- Suggested patch:")
                lines.append("```sql")
                lines.append(q.suggested_patch.rstrip())
                lines.append("```")
            lines.append("")
        if self.notes:
            lines.append("## Notes")
            lines.extend(f"- {n}" for n in self.notes)
        return "\n".join(lines).rstrip() + "\n"


def build_certificate(
    *,
    run_id: str,
    asset_urn: str,
    asset_name: str,
    change: ProposedChange,
    risk: RiskAssessment,
    query_impacts: list[QueryImpact],
    notes: list[str] | None = None,
) -> BreakageCertificate:
    summary = CertificateSummary(
        breaks=sum(1 for q in query_impacts if q.verdict == QueryVerdict.BREAKS),
        safe=sum(1 for q in query_impacts if q.verdict == QueryVerdict.SAFE),
        unknown=sum(1 for q in query_impacts if q.verdict == QueryVerdict.UNKNOWN),
    )
    merge_allowed = summary.breaks == 0
    issued_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cert = BreakageCertificate(
        run_id=run_id,
        issued_at=issued_at,
        asset_urn=asset_urn,
        asset_name=asset_name,
        change=change,
        risk_level=risk.level.value,
        risk_score=risk.score,
        queries=query_impacts,
        summary=summary,
        merge_allowed=merge_allowed,
        notes=notes or [],
    )
    cert.content_hash = _hash_certificate(cert)
    return cert


def _hash_certificate(cert: BreakageCertificate) -> str:
    payload = cert.model_dump(mode="json")
    payload.pop("content_hash", None)
    payload.pop("issued_at", None)  # stable hash across re-issue of same findings
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def certificate_blocks_merge(cert: BreakageCertificate) -> bool:
    return not cert.merge_allowed
