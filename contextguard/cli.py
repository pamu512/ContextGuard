"""CLI: gen-examples + merge-gate check."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from contextguard.analysis import parse_proposed_change, score_risk
from contextguard.artifacts import (
    attach_certificate,
    build_fallback_artifacts,
    write_example_bundle,
)
from contextguard.certificate import BreakageCertificate, build_certificate, certificate_blocks_merge
from contextguard.models import (
    AnalysisResult,
    ColumnRef,
    DownstreamAsset,
    EvidenceBundle,
    OwnerRef,
    QuerySnippet,
)
from contextguard.query_impact import QueryVerdict, classify_queries

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

ORDERS = "urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)"


def _showcase_evidence(column: str) -> EvidenceBundle:
    return EvidenceBundle(
        asset_urn=ORDERS,
        asset_name="ecommerce.public.orders",
        schema_fields=[
            ColumnRef(urn=f"{ORDERS}.id", name="id", native_type="NUMBER"),
            ColumnRef(urn=f"{ORDERS}.amount", name="amount", native_type="NUMBER"),
            ColumnRef(urn=f"{ORDERS}.customer_email", name="customer_email", native_type="VARCHAR"),
            ColumnRef(urn=f"{ORDERS}.status", name="status", native_type="VARCHAR"),
        ],
        downstream=[
            DownstreamAsset(
                urn="urn:li:dashboard:(looker,revenue_overview)",
                name="Revenue Overview",
                entity_type="dashboard",
                is_critical=True,
                column=column,
            ),
            DownstreamAsset(
                urn="urn:li:dataset:(urn:li:dataPlatform:dbt,mart.order_metrics,PROD)",
                name="mart.order_metrics",
                column=column,
            ),
        ],
        owners=[
            OwnerRef(
                urn="urn:li:corpuser:data-platform",
                name="Data Platform",
                email="data-platform@example.com",
            )
        ],
        queries=[
            QuerySnippet(query=f"select {column} from ecommerce.public.orders"),
            QuerySnippet(query="select id, status from ecommerce.public.orders"),
        ],
        quality_issues=["Freshness assertion delayed 2h"],
    )


def build_offline_result(
    raw_input: str,
    evidence: EvidenceBundle,
    *,
    sql_before: str | None = None,
    sql_after: str | None = None,
) -> AnalysisResult:
    change = parse_proposed_change(
        raw_input,
        evidence.asset_urn,
        sql_before=sql_before,
        sql_after=sql_after,
    )
    risk = score_risk(change, evidence)
    impacts = classify_queries(change, evidence)
    breaks = sum(1 for q in impacts if q.verdict == QueryVerdict.BREAKS)
    if breaks:
        from contextguard.agent import _level_for_score

        bumped = min(100, risk.score + min(25, breaks * 10))
        risk = risk.model_copy(
            update={
                "score": bumped,
                "reasons": list(risk.reasons)
                + [f"{breaks} known quer(ies) classified BREAKS by certificate engine"],
                "level": _level_for_score(bumped),
            }
        )
    arts = build_fallback_artifacts(change, evidence, risk)
    run_id = str(uuid.uuid4())
    cert = build_certificate(
        run_id=run_id,
        asset_urn=evidence.asset_urn,
        asset_name=evidence.asset_name,
        change=change,
        risk=risk,
        query_impacts=impacts,
        notes=list(evidence.unknowns),
    )
    arts = attach_certificate(arts, cert, impacts)
    return AnalysisResult(
        change=change,
        evidence=evidence,
        risk=risk,
        artifacts=arts,
        run_id=run_id,
        certificate=cert.model_dump(mode="json"),
    )


def generate_examples() -> None:
    breaking = build_offline_result("DROP COLUMN amount", _showcase_evidence("amount"))
    write_example_bundle(breaking, EXAMPLES / "breaking-drop-amount")

    evidence_safe = _showcase_evidence("status")
    evidence_safe.downstream = []
    evidence_safe.queries = [
        QuerySnippet(query="select id from ecommerce.public.orders"),
    ]
    evidence_safe.quality_issues = []
    safe = build_offline_result(
        "change column status from VARCHAR to VARCHAR",
        evidence_safe,
    )
    write_example_bundle(safe, EXAMPLES / "safe-status-type-noop")
    print(f"Wrote examples under {EXAMPLES}")


def check_certificate(
    path: Path,
    *,
    allow_breakage: bool = False,
    allow_unknown: bool = True,
) -> int:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cert = BreakageCertificate.model_validate(raw)
    print(f"Certificate {cert.version} hash={cert.content_hash}")
    print(
        f"BREAKS={cert.summary.breaks} SAFE={cert.summary.safe} "
        f"UNKNOWN={cert.summary.unknown} merge_allowed={cert.merge_allowed}"
    )
    if certificate_blocks_merge(cert) and not allow_breakage:
        print("FAIL: merge blocked — known queries BREAKS. "
              "Fix consumers or pass --allow-breakage / label allow-breakage.")
        return 1
    if cert.summary.unknown and not allow_unknown:
        print("FAIL: UNKNOWN query verdicts present and --strict-unknown set")
        return 1
    print("PASS: ContextGuard certificate allows merge")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="contextguard")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("gen-examples", help="Regenerate checked-in example bundles")

    check = sub.add_parser(
        "check",
        help="Merge gate: fail if breakage_certificate.json has BREAKS",
    )
    check.add_argument(
        "certificate",
        type=Path,
        help="Path to breakage_certificate.json",
    )
    check.add_argument(
        "--allow-breakage",
        action="store_true",
        help="Allow merge even when BREAKS > 0 (override)",
    )
    check.add_argument(
        "--strict-unknown",
        action="store_true",
        help="Also fail when UNKNOWN > 0",
    )

    args = parser.parse_args(argv)
    if args.cmd == "gen-examples":
        generate_examples()
        return
    if args.cmd == "check":
        code = check_certificate(
            args.certificate,
            allow_breakage=args.allow_breakage,
            allow_unknown=not args.strict_unknown,
        )
        raise SystemExit(code)


if __name__ == "__main__":
    main()
