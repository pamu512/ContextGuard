# ContextGuard Breakage Certificate (`cgcert/v1`)

- **Run:** `98c0d0b2-8cd6-4ba8-b6be-fe19192e7a22`
- **Issued:** 2026-07-25T02:15:41Z
- **Asset:** `ecommerce.public.orders` (`urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`)
- **Change:** `type_change` status → VARCHAR
- **Risk:** MEDIUM (27)
- **Merge allowed:** YES
- **Hash:** `b7e1e8957e93da3f`

## Summary
- BREAKS: **0**
- SAFE: **1**
- UNKNOWN: **0**

## Query verdicts
### 1. `SAFE`
- Query: `select id from ecommerce.public.orders`
- Reason: Query does not reference `status`
- Evidence: `urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`
