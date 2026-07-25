## Breakage Certificate

- Merge allowed: **YES**
- BREAKS / SAFE / UNKNOWN: 0 / 1 / 0
- Hash: `cc8cc1b446a8b6c0`

# ContextGuard Impact Report

**Asset:** `ecommerce.public.orders` (`urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`)
**Change:** `type_change`
**Risk:** MEDIUM (score 27)

## Why this matters
- Type changes can break casts, joins, and BI calculations
- No downstream dependencies found in DataHub lineage
- 1 known quer(ies) reference this asset
- 1 owner(s) should be notified

## Evidence
- Schema fields: 4
- Downstream: 0
- Owners: 1
- Queries: 1

## Unknowns
- None reported

## Impact claims
- No downstream dependents found in retrieved lineage — evidence: `urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`