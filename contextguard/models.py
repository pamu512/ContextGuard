"""Typed models for changes, evidence, risk, and artifacts."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ChangeType(str, Enum):
    DROP_COLUMN = "drop_column"
    RENAME_COLUMN = "rename_column"
    TYPE_CHANGE = "type_change"
    MODEL_SQL_REPLACEMENT = "model_sql_replacement"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ProposedChange(BaseModel):
    change_type: ChangeType
    asset_urn: str = Field(min_length=1)
    column: str | None = None
    new_column: str | None = None
    old_type: str | None = None
    new_type: str | None = None
    sql_before: str | None = None
    sql_after: str | None = None
    raw_input: str = ""

    @field_validator("asset_urn")
    @classmethod
    def strip_urn(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("asset_urn is required")
        return cleaned


class ColumnRef(BaseModel):
    urn: str
    name: str
    native_type: str | None = None


class DownstreamAsset(BaseModel):
    urn: str
    name: str
    entity_type: str = "dataset"
    is_critical: bool = False
    column: str | None = None


class OwnerRef(BaseModel):
    urn: str
    name: str
    email: str | None = None


class QuerySnippet(BaseModel):
    query: str
    source: str | None = None


class EvidenceBundle(BaseModel):
    asset_urn: str
    asset_name: str
    schema_fields: list[ColumnRef] = Field(default_factory=list)
    downstream: list[DownstreamAsset] = Field(default_factory=list)
    owners: list[OwnerRef] = Field(default_factory=list)
    queries: list[QuerySnippet] = Field(default_factory=list)
    quality_issues: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    raw_tool_payloads: dict[str, Any] = Field(default_factory=dict)


class ImpactClaim(BaseModel):
    claim: str
    evidence_urns: list[str] = Field(min_length=1)
    severity_note: str | None = None


class RiskAssessment(BaseModel):
    level: RiskLevel
    score: int = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    affected_assets: list[DownstreamAsset] = Field(default_factory=list)
    owner_count: int = 0
    query_usage_count: int = 0
    quality_issue_count: int = 0


class GeneratedArtifacts(BaseModel):
    impact_report_md: str
    compatibility_sql: str
    dbt_tests_yml: str
    migration_checklist_md: str
    owner_messages: list[str] = Field(default_factory=list)
    impact_claims: list[ImpactClaim] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    change: ProposedChange
    evidence: EvidenceBundle
    risk: RiskAssessment
    artifacts: GeneratedArtifacts
    run_id: str
    writeback_document_urn: str | None = None
