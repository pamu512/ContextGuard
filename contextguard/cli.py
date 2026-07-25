"""CLI: gen-examples, check, certify."""

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
from contextguard.change_spec import (
    change_request_to_proposed,
    load_change_request,
    load_evidence_fixture,
)
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


def showcase_evidence() -> EvidenceBundle:
    """Richer fixture: qualified cols, SELECT *, safe query, dashboard lineage."""
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
                column="amount",
            ),
            DownstreamAsset(
                urn="urn:li:dataset:(urn:li:dataPlatform:dbt,mart.order_metrics,PROD)",
                name="mart.order_metrics",
                column="amount",
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
            QuerySnippet(
                query="select o.amount, o.customer_email from ecommerce.public.orders o",
                source="looker:revenue_overview",
            ),
            QuerySnippet(
                query="select * from ecommerce.public.orders where status = 'complete'",
                source="adhoc:finance",
            ),
            QuerySnippet(
                query="select id, status from ecommerce.public.orders",
                source="dbt:staging",
            ),
            QuerySnippet(
                query="select sum(amount) as gmv from ecommerce.public.orders",
                source="metrics:gmv",
            ),
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
    return _result_from_change(change, evidence)


def _result_from_change(change, evidence: EvidenceBundle) -> AnalysisResult:
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
    evidence = showcase_evidence()
    breaking = build_offline_result("DROP COLUMN amount", evidence)
    write_example_bundle(breaking, EXAMPLES / "breaking-drop-amount")

    evidence_safe = showcase_evidence()
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

    # Checked-in evidence fixture for CI certify
    fixture_dir = EXAMPLES / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    (fixture_dir / "orders_evidence.json").write_text(
        showcase_evidence().model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
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
        print(
            "FAIL: merge blocked — known queries BREAKS. "
            "Fix consumers or pass --allow-breakage / label allow-breakage."
        )
        return 1
    if cert.summary.unknown and not allow_unknown:
        print("FAIL: UNKNOWN query verdicts present and --strict-unknown set")
        return 1
    print("PASS: ContextGuard certificate allows merge")
    return 0


def certify_change(
    change_path: Path,
    *,
    evidence_path: Path | None,
    out_dir: Path,
    repo_root: Path = ROOT,
) -> AnalysisResult:
    req = load_change_request(change_path)
    change = change_request_to_proposed(req)
    if evidence_path is None and req.evidence_fixture:
        evidence_path = repo_root / req.evidence_fixture
    if evidence_path is None:
        raise SystemExit("certify requires --evidence or evidence_fixture in the change file")
    evidence = load_evidence_fixture(evidence_path)
    # Ensure URN matches / override to change request URN
    evidence = evidence.model_copy(update={"asset_urn": req.asset_urn})
    result = _result_from_change(change, evidence)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_example_bundle(result, out_dir)
    # Also write a short PR comment markdown
    cert = BreakageCertificate.model_validate(result.certificate)
    (out_dir / "pr_comment.md").write_text(_pr_comment(cert, change_path), encoding="utf-8")
    print(f"Wrote certificate bundle to {out_dir}")
    print(
        f"merge_allowed={cert.merge_allowed} "
        f"BREAKS={cert.summary.breaks} SAFE={cert.summary.safe} UNKNOWN={cert.summary.unknown}"
    )
    return result


def _pr_comment(cert: BreakageCertificate, change_path: Path) -> str:
    status = "ALLOW MERGE" if cert.merge_allowed else "BLOCK MERGE"
    lines = [
        "## ContextGuard Breakage Certificate",
        "",
        f"**Status:** `{status}`",
        f"**Change file:** `{change_path.as_posix()}`",
        f"**Asset:** `{cert.asset_name}`",
        f"**Risk:** {cert.risk_level.upper()} ({cert.risk_score})",
        f"**BREAKS / SAFE / UNKNOWN:** "
        f"{cert.summary.breaks} / {cert.summary.safe} / {cert.summary.unknown}",
        f"**Hash:** `{cert.content_hash}`",
        "",
        "| Verdict | Query | Reason |",
        "|---|---|---|",
    ]
    for q in cert.queries:
        preview = (q.query or "").replace("|", "\\|").replace("\n", " ")[:80]
        reason = q.reason.replace("|", "\\|")
        lines.append(f"| `{q.verdict.value}` | `{preview}` | {reason} |")
    lines.extend(
        [
            "",
            "> DataHub Impact Analysis lists dependents. "
            "This certificate proves which **known queries** break.",
            "",
            "Override with PR label `allow-breakage` only after owner sign-off.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="contextguard")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("gen-examples", help="Regenerate checked-in example bundles")

    check = sub.add_parser(
        "check",
        help="Merge gate: fail if breakage_certificate.json has BREAKS",
    )
    check.add_argument("certificate", type=Path)
    check.add_argument("--allow-breakage", action="store_true")
    check.add_argument("--strict-unknown", action="store_true")

    certify = sub.add_parser(
        "certify",
        help="Issue a certificate from changes/*.json + evidence fixture",
    )
    certify.add_argument("change", type=Path, help="Path to change request JSON")
    certify.add_argument(
        "--evidence",
        type=Path,
        default=None,
        help="Evidence fixture JSON (or set evidence_fixture on the change)",
    )
    certify.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/certificate"),
        help="Output directory for certificate bundle",
    )
    certify.add_argument(
        "--fail-on-breakage",
        action="store_true",
        help="Exit 1 when merge_allowed is false",
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
    if args.cmd == "certify":
        result = certify_change(
            args.change,
            evidence_path=args.evidence,
            out_dir=args.out_dir,
        )
        if args.fail_on_breakage and result.certificate and not result.certificate.get(
            "merge_allowed", True
        ):
            raise SystemExit(1)
        return


if __name__ == "__main__":
    main()
