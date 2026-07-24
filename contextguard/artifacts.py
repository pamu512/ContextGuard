"""Artifact packaging and schema validation for generated SQL/dbt."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from contextguard.models import (
    AnalysisResult,
    EvidenceBundle,
    GeneratedArtifacts,
    ProposedChange,
    RiskAssessment,
)

_IDENT = re.compile(r"\b([A-Za-z_][\w]*)\b")


class ArtifactValidationError(ValueError):
    pass


def validate_sql_against_schema(sql: str, evidence: EvidenceBundle) -> list[str]:
    """Return warnings when SQL references unknown columns (best-effort)."""
    known = {f.name.lower() for f in evidence.schema_fields}
    if not known:
        return ["Schema unknown — SQL column references could not be validated"]
    # Skip SQL keywords
    keywords = {
        "select",
        "from",
        "where",
        "and",
        "or",
        "as",
        "join",
        "left",
        "right",
        "inner",
        "outer",
        "on",
        "group",
        "by",
        "order",
        "limit",
        "with",
        "case",
        "when",
        "then",
        "else",
        "end",
        "null",
        "is",
        "not",
        "in",
        "create",
        "view",
        "table",
        "alter",
        "drop",
        "column",
        "rename",
        "to",
        "set",
        "type",
        "compat",
        "coalesce",
        "cast",
        "true",
        "false",
        "distinct",
        "count",
        "sum",
        "avg",
        "min",
        "max",
    }
    refs = {m.group(1).lower() for m in _IDENT.finditer(sql)} - keywords
    unknown = sorted(refs - known)
    return [f"Unknown column reference: `{col}`" for col in unknown]


def build_fallback_artifacts(
    change: ProposedChange,
    evidence: EvidenceBundle,
    risk: RiskAssessment,
) -> GeneratedArtifacts:
    col = change.column or "column"
    claims = []
    for asset in risk.affected_assets:
        claims.append(
            {
                "claim": f"Downstream asset `{asset.name}` may break",
                "evidence_urns": [asset.urn, evidence.asset_urn],
            }
        )
    if not claims:
        claims.append(
            {
                "claim": "No downstream dependents found in retrieved lineage",
                "evidence_urns": [evidence.asset_urn],
            }
        )

    from contextguard.models import ImpactClaim

    impact_claims = [ImpactClaim(**c) for c in claims]

    report = [
        f"# ContextGuard Impact Report",
        "",
        f"**Asset:** `{evidence.asset_name}` (`{evidence.asset_urn}`)",
        f"**Change:** `{change.change_type.value}`",
        f"**Risk:** {risk.level.value.upper()} (score {risk.score})",
        "",
        "## Why this matters",
        *[f"- {r}" for r in risk.reasons],
        "",
        "## Evidence",
        f"- Schema fields: {len(evidence.schema_fields)}",
        f"- Downstream: {len(evidence.downstream)}",
        f"- Owners: {len(evidence.owners)}",
        f"- Queries: {len(evidence.queries)}",
        "",
        "## Unknowns",
        *(
            [f"- {u}" for u in evidence.unknowns]
            if evidence.unknowns
            else ["- None reported"]
        ),
        "",
        "## Impact claims",
        *[
            f"- {c.claim} — evidence: {', '.join(f'`{u}`' for u in c.evidence_urns)}"
            for c in impact_claims
        ],
    ]

    if change.change_type.value == "drop_column":
        sql = (
            f"-- Compatibility view preserving `{col}` as NULL during migration\n"
            f"CREATE OR REPLACE VIEW {evidence.asset_name}_compat AS\n"
            f"SELECT * EXCLUDE ({col}), CAST(NULL AS VARCHAR) AS {col}\n"
            f"FROM {evidence.asset_name};\n"
        )
        tests = (
            f"version: 2\nmodels:\n  - name: {evidence.asset_name}\n"
            f"    columns:\n      - name: {col}\n"
            f"        tests:\n          - accepted_values:\n"
            f"              values: []  # expect zero rows using dropped column post-cutover\n"
        )
    elif change.change_type.value == "rename_column":
        new_col = change.new_column or f"{col}_new"
        sql = (
            f"-- Dual-write compatibility: expose both old and new names\n"
            f"CREATE OR REPLACE VIEW {evidence.asset_name}_compat AS\n"
            f"SELECT * EXCLUDE ({col}), {col} AS {new_col}, {col} AS {col}\n"
            f"FROM {evidence.asset_name};\n"
        )
        tests = (
            f"version: 2\nmodels:\n  - name: {evidence.asset_name}\n"
            f"    columns:\n      - name: {new_col}\n        tests: [not_null]\n"
            f"      - name: {col}\n        tests: [not_null]\n"
        )
    elif change.change_type.value == "type_change":
        new_type = change.new_type or "VARCHAR"
        sql = (
            f"-- Soft type migration via casted compatibility column\n"
            f"CREATE OR REPLACE VIEW {evidence.asset_name}_compat AS\n"
            f"SELECT * EXCLUDE ({col}), CAST({col} AS {new_type}) AS {col}\n"
            f"FROM {evidence.asset_name};\n"
        )
        tests = (
            f"version: 2\nmodels:\n  - name: {evidence.asset_name}\n"
            f"    columns:\n      - name: {col}\n        tests: [not_null]\n"
        )
    else:
        sql = (
            f"-- Review model SQL replacement carefully\n"
            f"-- BEFORE:\n-- { (change.sql_before or '').replace(chr(10), chr(10)+'-- ') }\n"
            f"-- AFTER:\n{change.sql_after or '-- (missing sql_after)'}\n"
        )
        tests = (
            f"version: 2\nmodels:\n  - name: {evidence.asset_name}\n"
            f"    tests:\n      - dbt_utils.equal_rowcount:\n"
            f"          compare_model: ref('{evidence.asset_name}_compat')\n"
        )

    checklist = [
        "# Migration checklist",
        "",
        f"1. Confirm risk score ({risk.score}) with owners.",
        "2. Open PR with compatibility SQL + dbt tests from this package.",
        "3. Notify downstream owners (messages below).",
        "4. Deploy compatibility view / dual-write period.",
        "5. Migrate consumers, then remove compatibility shim.",
        "6. Re-run ContextGuard analysis after cutover.",
    ]
    messages = []
    for owner in evidence.owners:
        who = owner.email or owner.name
        messages.append(
            f"Hi {who} — proposed `{change.change_type.value}` on "
            f"`{evidence.asset_name}` ({evidence.asset_urn}) has risk "
            f"{risk.level.value}. Please review the compatibility plan before merge."
        )
    if not messages:
        messages.append(
            f"Owners unknown for `{evidence.asset_urn}`. "
            f"Post the impact report in the data-platform channel."
        )

    return GeneratedArtifacts(
        impact_report_md="\n".join(report),
        compatibility_sql=sql,
        dbt_tests_yml=tests,
        migration_checklist_md="\n".join(checklist),
        owner_messages=messages,
        impact_claims=impact_claims,
    )


def package_artifacts_zip(result: AnalysisResult) -> bytes:
    buf = io.BytesIO()
    arts = result.artifacts
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("impact_report.md", arts.impact_report_md)
        zf.writestr("compatibility.sql", arts.compatibility_sql)
        zf.writestr("schema.yml", arts.dbt_tests_yml)
        zf.writestr("migration_checklist.md", arts.migration_checklist_md)
        zf.writestr("owner_messages.txt", "\n\n".join(arts.owner_messages) + "\n")
        zf.writestr(
            "meta.json",
            result.model_dump_json(
                indent=2,
                exclude={"evidence": {"raw_tool_payloads": True}},
            ),
        )
    return buf.getvalue()


def write_example_bundle(result: AnalysisResult, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    arts = result.artifacts
    (directory / "impact_report.md").write_text(arts.impact_report_md, encoding="utf-8")
    (directory / "compatibility.sql").write_text(arts.compatibility_sql, encoding="utf-8")
    (directory / "schema.yml").write_text(arts.dbt_tests_yml, encoding="utf-8")
    (directory / "migration_checklist.md").write_text(
        arts.migration_checklist_md, encoding="utf-8"
    )
    (directory / "owner_messages.txt").write_text(
        "\n\n".join(arts.owner_messages) + "\n", encoding="utf-8"
    )
    # Strip secrets/raw payloads from checked-in example
    safe = result.model_copy(deep=True)
    safe.evidence.raw_tool_payloads = {}
    (directory / "result.json").write_text(safe.model_dump_json(indent=2), encoding="utf-8")


def ensure_claims_have_urns(artifacts: GeneratedArtifacts) -> None:
    for claim in artifacts.impact_claims:
        if not claim.evidence_urns:
            raise ArtifactValidationError(f"Impact claim missing evidence URNs: {claim.claim}")
