# ContextGuard Breakage Certificate (`cgcert/v1`)

- **Run:** `d15bd50d-cba1-43b2-9489-758bf5c1efdb`
- **Issued:** 2026-07-25T23:44:00Z
- **Asset:** `ecommerce.public.orders` (`urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`)
- **Change:** `type_change` status → VARCHAR
- **Risk:** MEDIUM (27)
- **Merge allowed:** YES
- **Hash:** `cc8cc1b446a8b6c0`

## Summary
- BREAKS: **0**
- SAFE: **1**
- UNKNOWN: **0**

## Query verdicts
### 1. `SAFE`
- Query: `select id from ecommerce.public.orders`
- Reason: Query does not reference `status`
- Evidence: `urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`
