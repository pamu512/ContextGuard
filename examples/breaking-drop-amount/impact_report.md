## Breakage Certificate

- Merge allowed: **NO**
- BREAKS / SAFE / UNKNOWN: 1 / 1 / 0
- Hash: `587c8802cf24d4c1`

# ContextGuard Impact Report

**Asset:** `ecommerce.public.orders` (`urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`)
**Change:** `drop_column`
**Risk:** HIGH (score 72)

## Why this matters
- Dropping a column is a breaking schema change
- 2 downstream asset(s) depend on this asset/column
- 1 critical downstream asset(s) affected
- 2 known quer(ies) reference this asset
- 1 owner(s) should be notified
- 1 existing quality issue(s) on this asset
- 1 known quer(ies) classified BREAKS by certificate engine

## Evidence
- Schema fields: 4
- Downstream: 2
- Owners: 1
- Queries: 2

## Unknowns
- None reported

## Impact claims
- Downstream asset `Revenue Overview` may break — evidence: `urn:li:dashboard:(looker,revenue_overview)`, `urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`
- Downstream asset `mart.order_metrics` may break — evidence: `urn:li:dataset:(urn:li:dataPlatform:dbt,mart.order_metrics,PROD)`, `urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`