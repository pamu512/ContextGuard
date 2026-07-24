"""CLI helpers for regenerating example bundles."""

from __future__ import annotations

import argparse
import asyncio
import uuid
from pathlib import Path

from contextguard.analysis import parse_proposed_change, score_risk
from contextguard.artifacts import build_fallback_artifacts, write_example_bundle
from contextguard.models import (
    AnalysisResult,
    ColumnRef,
    DownstreamAsset,
    EvidenceBundle,
    OwnerRef,
    QuerySnippet,
)

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
        queries=[QuerySnippet(query=f"select {column} from ecommerce.public.orders")],
        quality_issues=["Freshness assertion delayed 2h"],
    )


def generate_examples() -> None:
    breaking = parse_proposed_change("DROP COLUMN amount", ORDERS)
    evidence = _showcase_evidence("amount")
    risk = score_risk(breaking, evidence)
    arts = build_fallback_artifacts(breaking, evidence, risk)
    write_example_bundle(
        AnalysisResult(
            change=breaking,
            evidence=evidence,
            risk=risk,
            artifacts=arts,
            run_id=str(uuid.uuid4()),
        ),
        EXAMPLES / "breaking-drop-amount",
    )

    safe = parse_proposed_change(
        "change column status from VARCHAR to VARCHAR",
        ORDERS,
    )
    # Same-type change with no dependents on that column → lower risk
    evidence_safe = _showcase_evidence("status")
    evidence_safe.downstream = []
    evidence_safe.queries = []
    evidence_safe.quality_issues = []
    risk_safe = score_risk(safe, evidence_safe)
    arts_safe = build_fallback_artifacts(safe, evidence_safe, risk_safe)
    write_example_bundle(
        AnalysisResult(
            change=safe,
            evidence=evidence_safe,
            risk=risk_safe,
            artifacts=arts_safe,
            run_id=str(uuid.uuid4()),
        ),
        EXAMPLES / "safe-status-type-noop",
    )
    print(f"Wrote examples under {EXAMPLES}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="contextguard")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen-examples", help="Regenerate checked-in example bundles")
    args = parser.parse_args()
    if args.cmd == "gen-examples":
        generate_examples()


if __name__ == "__main__":
    main()
