"""Change request files for CI certify flow."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from contextguard.analysis import parse_proposed_change
from contextguard.models import EvidenceBundle, ProposedChange


class ChangeRequest(BaseModel):
    """Declarative schema/dbt change checked in under changes/."""

    asset_urn: str = Field(min_length=1)
    description: str = Field(min_length=1)
    sql_before: str | None = None
    sql_after: str | None = None
    evidence_fixture: str | None = None  # path relative to repo root


def load_change_request(path: Path) -> ChangeRequest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ChangeRequest.model_validate(data)


def change_request_to_proposed(req: ChangeRequest) -> ProposedChange:
    return parse_proposed_change(
        req.description,
        req.asset_urn,
        sql_before=req.sql_before,
        sql_after=req.sql_after,
    )


def load_evidence_fixture(path: Path) -> EvidenceBundle:
    raw = json.loads(path.read_text(encoding="utf-8"))
    # Accept full AnalysisResult JSON or bare EvidenceBundle
    if "evidence" in raw and isinstance(raw["evidence"], dict):
        return EvidenceBundle.model_validate(raw["evidence"])
    return EvidenceBundle.model_validate(raw)
