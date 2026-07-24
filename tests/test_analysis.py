"""Tests for change parsing and risk scoring."""

import pytest

from contextguard.analysis import (
    UnsupportedChangeError,
    column_exists,
    parse_proposed_change,
    score_risk,
)
from contextguard.models import (
    ChangeType,
    ColumnRef,
    DownstreamAsset,
    EvidenceBundle,
    OwnerRef,
    QuerySnippet,
    RiskLevel,
)

URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,db.schema.orders,PROD)"


def test_parse_drop_column_natural_language():
    change = parse_proposed_change("Drop column customer_email", URN)
    assert change.change_type == ChangeType.DROP_COLUMN
    assert change.column == "customer_email"


def test_parse_alter_drop_sql():
    change = parse_proposed_change(
        "ALTER TABLE orders DROP COLUMN amount_usd;",
        URN,
    )
    assert change.change_type == ChangeType.DROP_COLUMN
    assert change.column == "amount_usd"


def test_parse_rename():
    change = parse_proposed_change("rename column user_id to customer_id", URN)
    assert change.change_type == ChangeType.RENAME_COLUMN
    assert change.column == "user_id"
    assert change.new_column == "customer_id"


def test_parse_type_change():
    change = parse_proposed_change(
        "change column amount from NUMBER to VARCHAR",
        URN,
    )
    assert change.change_type == ChangeType.TYPE_CHANGE
    assert change.column == "amount"
    assert change.old_type == "NUMBER"
    assert change.new_type == "VARCHAR"


def test_parse_model_sql_replacement():
    change = parse_proposed_change(
        "replace the dbt model",
        URN,
        sql_before="select id from orders",
        sql_after="select id, status from orders",
    )
    assert change.change_type == ChangeType.MODEL_SQL_REPLACEMENT
    assert "status" in (change.sql_after or "")


def test_parse_empty_raises():
    with pytest.raises(UnsupportedChangeError):
        parse_proposed_change("   ", URN)


def test_parse_unsupported_raises():
    with pytest.raises(UnsupportedChangeError):
        parse_proposed_change("add a brand new table for invoices", URN)


def test_column_exists():
    evidence = EvidenceBundle(
        asset_urn=URN,
        asset_name="orders",
        schema_fields=[ColumnRef(urn=f"{URN}.amount", name="amount")],
    )
    assert column_exists(evidence, "amount")
    assert not column_exists(evidence, "missing")


def test_score_risk_critical_with_downstream():
    change = parse_proposed_change("drop column amount", URN)
    evidence = EvidenceBundle(
        asset_urn=URN,
        asset_name="orders",
        schema_fields=[ColumnRef(urn=f"{URN}.amount", name="amount")],
        downstream=[
            DownstreamAsset(
                urn="urn:li:dataset:(urn:li:dataPlatform:looker,dash.revenue,PROD)",
                name="Revenue Dashboard",
                entity_type="dashboard",
                is_critical=True,
                column="amount",
            ),
            DownstreamAsset(
                urn="urn:li:dataset:(urn:li:dataPlatform:dbt,mart.orders,PROD)",
                name="mart_orders",
                column="amount",
            ),
        ],
        owners=[OwnerRef(urn="urn:li:corpuser:alice", name="Alice", email="a@x.com")],
        queries=[QuerySnippet(query="select amount from orders")],
        quality_issues=["Freshness SLA breached"],
    )
    risk = score_risk(change, evidence)
    assert risk.level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
    assert risk.score >= 50
    assert len(risk.affected_assets) == 2


def test_score_risk_low_when_no_deps_and_unknown_column():
    change = parse_proposed_change("drop column ghost_col", URN)
    evidence = EvidenceBundle(
        asset_urn=URN,
        asset_name="orders",
        schema_fields=[ColumnRef(urn=f"{URN}.id", name="id")],
    )
    risk = score_risk(change, evidence)
    assert risk.score >= 35  # drop + missing column
    assert any("not found" in r.lower() for r in risk.reasons)
