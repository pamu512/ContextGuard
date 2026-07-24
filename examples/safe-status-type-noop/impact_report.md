# ContextGuard Impact Report

**Asset:** `ecommerce.public.orders` (`urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`)
**Change:** `type_change`
**Risk:** MEDIUM (score 25)

## Why this matters
- Type changes can break casts, joins, and BI calculations
- No downstream dependencies found in DataHub lineage
- 1 owner(s) should be notified

## Evidence
- Schema fields: 4
- Downstream: 0
- Owners: 1
- Queries: 0

## Unknowns
- None reported

## Impact claims
- No downstream dependents found in retrieved lineage — evidence: `urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`