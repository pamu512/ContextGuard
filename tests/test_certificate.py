"""Tests for query-aware breakage certificates."""

from contextguard.certificate import build_certificate, certificate_blocks_merge
from contextguard.cli import build_offline_result, check_certificate
from contextguard.models import (
    ChangeType,
    ColumnRef,
    EvidenceBundle,
    ProposedChange,
    QuerySnippet,
    RiskAssessment,
    RiskLevel,
)
from contextguard.query_impact import QueryVerdict, classify_queries, extract_identifiers


URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)"


def _evidence(queries):
    return EvidenceBundle(
        asset_urn=URN,
        asset_name="orders",
        schema_fields=[
            ColumnRef(urn=f"{URN}.amount", name="amount"),
            ColumnRef(urn=f"{URN}.id", name="id"),
            ColumnRef(urn=f"{URN}.status", name="status"),
        ],
        queries=[QuerySnippet(query=q) for q in queries],
    )


def test_drop_column_breaks_referencing_query():
    change = ProposedChange(
        change_type=ChangeType.DROP_COLUMN, asset_urn=URN, column="amount"
    )
    impacts = classify_queries(
        change, _evidence(["select amount from orders", "select id from orders"])
    )
    assert impacts[0].verdict == QueryVerdict.BREAKS
    assert impacts[0].suggested_patch
    assert impacts[1].verdict == QueryVerdict.SAFE


def test_rename_breaks_old_name():
    change = ProposedChange(
        change_type=ChangeType.RENAME_COLUMN,
        asset_urn=URN,
        column="amount",
        new_column="amount_usd",
    )
    impacts = classify_queries(change, _evidence(["select amount from orders"]))
    assert impacts[0].verdict == QueryVerdict.BREAKS
    assert "amount_usd" in (impacts[0].suggested_patch or "")


def test_type_noop_safe():
    change = ProposedChange(
        change_type=ChangeType.TYPE_CHANGE,
        asset_urn=URN,
        column="status",
        old_type="VARCHAR",
        new_type="VARCHAR",
    )
    impacts = classify_queries(change, _evidence(["select status from orders"]))
    assert impacts[0].verdict == QueryVerdict.SAFE


def test_certificate_blocks_merge_on_breaks():
    change = ProposedChange(
        change_type=ChangeType.DROP_COLUMN, asset_urn=URN, column="amount"
    )
    evidence = _evidence(["select amount from orders"])
    impacts = classify_queries(change, evidence)
    cert = build_certificate(
        run_id="r1",
        asset_urn=URN,
        asset_name="orders",
        change=change,
        risk=RiskAssessment(level=RiskLevel.HIGH, score=70),
        query_impacts=impacts,
    )
    assert cert.summary.breaks == 1
    assert certificate_blocks_merge(cert)
    assert "BREAKS" in cert.to_markdown()


def test_cli_check_fail_and_pass(tmp_path):
    breaking = build_offline_result(
        "DROP COLUMN amount",
        _evidence(["select amount from orders"]),
    )
    path = tmp_path / "breakage_certificate.json"
    path.write_text(
        __import__("json").dumps(breaking.certificate),
        encoding="utf-8",
    )
    assert check_certificate(path) == 1
    assert check_certificate(path, allow_breakage=True) == 0

    safe = build_offline_result(
        "change column status from VARCHAR to VARCHAR",
        _evidence(["select id from orders"]),
    )
    path.write_text(__import__("json").dumps(safe.certificate), encoding="utf-8")
    assert check_certificate(path) == 0


def test_extract_identifiers_skips_keywords():
    ids = extract_identifiers("SELECT amount FROM orders WHERE id = 1")
    assert "amount" in ids
    assert "select" not in ids


def test_qualified_column_and_select_star_break():
    from contextguard.query_impact import references_column, has_select_star

    assert references_column("select o.amount from orders o", "amount")
    assert has_select_star("select * from ecommerce.public.orders")
    change = ProposedChange(
        change_type=ChangeType.DROP_COLUMN, asset_urn=URN, column="amount"
    )
    evidence = EvidenceBundle(
        asset_urn=URN,
        asset_name="ecommerce.public.orders",
        schema_fields=[
            ColumnRef(urn=f"{URN}.amount", name="amount"),
            ColumnRef(urn=f"{URN}.id", name="id"),
        ],
        queries=[
            QuerySnippet(query="select o.amount from ecommerce.public.orders o"),
            QuerySnippet(query="select * from ecommerce.public.orders"),
            QuerySnippet(query="select id from ecommerce.public.orders"),
        ],
    )
    impacts = classify_queries(change, evidence)
    assert impacts[0].verdict == QueryVerdict.BREAKS
    assert impacts[1].verdict == QueryVerdict.BREAKS
    assert impacts[2].verdict == QueryVerdict.SAFE


def test_certify_change_request(tmp_path):
    from contextguard.cli import certify_change, showcase_evidence

    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(showcase_evidence().model_dump_json(), encoding="utf-8")
    change_path = tmp_path / "drop.json"
    change_path.write_text(
        __import__("json").dumps(
            {
                "asset_urn": URN,
                "description": "DROP COLUMN amount",
                "evidence_fixture": str(evidence_path),
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    result = certify_change(change_path, evidence_path=evidence_path, out_dir=out)
    assert result.certificate["summary"]["breaks"] >= 2
    assert (out / "breakage_certificate.json").exists()
    assert (out / "pr_comment.md").exists()
