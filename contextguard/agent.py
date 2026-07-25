"""Evidence-grounded Gemini orchestration for ContextGuard."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from pydantic import ValidationError

from contextguard.analysis import parse_proposed_change, score_risk
from contextguard.artifacts import (
    attach_certificate,
    build_fallback_artifacts,
    ensure_claims_have_urns,
    validate_sql_against_schema,
)
from contextguard.certificate import build_certificate
from contextguard.config import Settings, get_settings
from contextguard.datahub import DataHubClient, DataHubError
from contextguard.models import (
    AnalysisResult,
    EvidenceBundle,
    GeneratedArtifacts,
    ProposedChange,
    RiskAssessment,
)
from contextguard.query_impact import QueryVerdict, classify_queries

logger = logging.getLogger(__name__)


class StaleRunError(RuntimeError):
    """Raised when a newer analysis superseded this run."""


class AgentError(RuntimeError):
    pass


class AnalysisOrchestrator:
    """Collect evidence → score risk → generate grounded artifacts."""

    def __init__(
        self,
        client: DataHubClient,
        settings: Settings | None = None,
        *,
        llm: Any | None = None,
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()
        self._llm = llm
        self._latest_run_id: str | None = None

    async def analyze(
        self,
        *,
        asset_urn: str,
        raw_input: str,
        sql_before: str | None = None,
        sql_after: str | None = None,
        uploaded_text: str | None = None,
        run_id: str | None = None,
    ) -> AnalysisResult:
        run_id = run_id or str(uuid.uuid4())
        self._latest_run_id = run_id

        change = parse_proposed_change(
            raw_input,
            asset_urn,
            sql_before=sql_before,
            sql_after=sql_after,
            uploaded_text=uploaded_text,
        )
        evidence = await self._client.collect_evidence(asset_urn, query_hint=raw_input)
        if not evidence.asset_urn:
            raise AgentError("Unresolved asset — DataHub returned empty evidence")

        risk = score_risk(change, evidence)
        impacts = classify_queries(change, evidence)
        breaks = sum(1 for q in impacts if q.verdict == QueryVerdict.BREAKS)
        if breaks:
            # Query proof raises severity beyond lineage-only scoring
            bumped = min(100, risk.score + min(25, breaks * 10))
            reasons = list(risk.reasons) + [
                f"{breaks} known quer(ies) classified BREAKS by certificate engine"
            ]
            risk = risk.model_copy(
                update={
                    "score": bumped,
                    "reasons": reasons,
                    "level": _level_for_score(bumped),
                }
            )

        artifacts = await self._generate_artifacts(change, evidence, risk)
        cert = build_certificate(
            run_id=run_id,
            asset_urn=evidence.asset_urn,
            asset_name=evidence.asset_name,
            change=change,
            risk=risk,
            query_impacts=impacts,
            notes=list(evidence.unknowns),
        )
        artifacts = attach_certificate(artifacts, cert, impacts)
        self._assert_not_stale(run_id)

        return AnalysisResult(
            change=change,
            evidence=evidence,
            risk=risk,
            artifacts=artifacts,
            run_id=run_id,
            certificate=cert.model_dump(mode="json"),
        )

    async def writeback(self, result: AnalysisResult) -> AnalysisResult:
        self._assert_not_stale(result.run_id)
        content = result.artifacts.certificate_md or result.artifacts.impact_report_md
        payload = await self._client.save_review_document(
            title=f"ContextGuard certificate: {result.evidence.asset_name}",
            content=content,
            related_urn=result.evidence.asset_urn,
            tag="contextguard-certificate",
        )
        doc = payload.get("document") if isinstance(payload, dict) else None
        urn = None
        if isinstance(doc, dict):
            urn = doc.get("urn") or doc.get("documentUrn")
        updated = result.model_copy(deep=True)
        updated.writeback_document_urn = str(urn) if urn else "saved"
        return updated

    def _assert_not_stale(self, run_id: str) -> None:
        if self._latest_run_id and run_id != self._latest_run_id:
            raise StaleRunError("A newer analysis run superseded this result")

    async def _generate_artifacts(
        self,
        change: ProposedChange,
        evidence: EvidenceBundle,
        risk: RiskAssessment,
    ) -> GeneratedArtifacts:
        fallback = build_fallback_artifacts(change, evidence, risk)
        if self._llm is None and not self._settings.google_api_key:
            ensure_claims_have_urns(fallback)
            return fallback

        try:
            generated = await self._llm_generate(change, evidence, risk, repair=False)
            ensure_claims_have_urns(generated)
            warnings = validate_sql_against_schema(generated.compatibility_sql, evidence)
            if warnings:
                generated.impact_report_md += "\n\n## Validation warnings\n" + "\n".join(
                    f"- {w}" for w in warnings
                )
            return generated
        except Exception as first_exc:  # noqa: BLE001
            logger.warning("LLM generation failed, attempting repair: %s", first_exc)
            try:
                generated = await self._llm_generate(
                    change, evidence, risk, repair=True, prior_error=str(first_exc)
                )
                ensure_claims_have_urns(generated)
                return generated
            except Exception as repair_exc:  # noqa: BLE001
                logger.warning("LLM repair failed, using deterministic fallback: %s", repair_exc)
                ensure_claims_have_urns(fallback)
                return fallback

    async def _llm_generate(
        self,
        change: ProposedChange,
        evidence: EvidenceBundle,
        risk: RiskAssessment,
        *,
        repair: bool,
        prior_error: str | None = None,
    ) -> GeneratedArtifacts:
        prompt = _build_prompt(change, evidence, risk, repair=repair, prior_error=prior_error)
        raw_text = await self._call_llm(prompt)
        data = _extract_json(raw_text)
        try:
            return GeneratedArtifacts.model_validate(data)
        except ValidationError as exc:
            # One-shot field repair for missing claims
            if "impact_claims" not in data:
                data["impact_claims"] = [
                    {
                        "claim": "See impact report",
                        "evidence_urns": [evidence.asset_urn],
                    }
                ]
                try:
                    return GeneratedArtifacts.model_validate(data)
                except ValidationError:
                    pass
            raise AgentError(f"Invalid LLM artifact schema: {exc}") from exc

    async def _call_llm(self, prompt: str) -> str:
        if self._llm is not None:
            result = self._llm(prompt)
            if hasattr(result, "__await__"):
                result = await result
            return str(result)

        from google import genai

        client = genai.Client(api_key=self._settings.google_api_key)
        response = client.models.generate_content(
            model=self._settings.gemini_model,
            contents=prompt,
        )
        text = getattr(response, "text", None)
        if not text:
            raise AgentError("Empty Gemini response")
        return text


def _build_prompt(
    change: ProposedChange,
    evidence: EvidenceBundle,
    risk: RiskAssessment,
    *,
    repair: bool,
    prior_error: str | None,
) -> str:
    evidence_json = evidence.model_dump(exclude={"raw_tool_payloads"})
    payload = {
        "change": change.model_dump(),
        "risk": risk.model_dump(),
        "evidence": evidence_json,
    }
    rules = [
        "You are ContextGuard. Produce merge-ready migration artifacts.",
        "ONLY use facts present in the evidence JSON. Mark missing facts as unknown.",
        "Every impact claim MUST include evidence_urns from the evidence.",
        "Do not invent owners, columns, or downstream assets.",
        "Return ONLY valid JSON matching GeneratedArtifacts:",
        "{"
        '"impact_report_md": string, '
        '"compatibility_sql": string, '
        '"dbt_tests_yml": string, '
        '"migration_checklist_md": string, '
        '"owner_messages": [string], '
        '"impact_claims": [{"claim": string, "evidence_urns": [string], "severity_note": string|null}]'
        "}",
    ]
    if repair:
        rules.append(f"Previous output failed validation: {prior_error}. Fix and return JSON only.")
    return "\n".join(rules) + "\n\nEVIDENCE:\n" + json.dumps(payload, indent=2)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [ln for ln in lines if not ln.startswith("```")]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        raise AgentError("LLM response did not contain JSON")
    return json.loads(text[start : end + 1])


def _level_for_score(score: int):
    from contextguard.models import RiskLevel

    if score >= 75:
        return RiskLevel.CRITICAL
    if score >= 50:
        return RiskLevel.HIGH
    if score >= 25:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


async def build_live_orchestrator(settings: Settings | None = None) -> AnalysisOrchestrator:
    settings = settings or get_settings()
    from contextguard.datahub import AdkMcpToolCaller

    caller = AdkMcpToolCaller(settings)
    await caller.connect()
    client = DataHubClient(caller, settings)
    return AnalysisOrchestrator(client, settings)
