# ContextGuard Breakage Certificate (`cgcert/v1`)

- **Run:** `a0b8d58e-1531-42ab-8395-982ad42b5a5c`
- **Issued:** 2026-07-25T02:15:41Z
- **Asset:** `ecommerce.public.orders` (`urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`)
- **Change:** `drop_column` amount
- **Risk:** HIGH (72)
- **Merge allowed:** NO
- **Hash:** `587c8802cf24d4c1`

## Summary
- BREAKS: **1**
- SAFE: **1**
- UNKNOWN: **0**

## Query verdicts
### 1. `BREAKS`
- Query: `select amount from ecommerce.public.orders`
- Reason: Query references dropped column `amount`
- Evidence: `urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`
- Suggested patch:
```sql
-- Consumer patch: stop selecting dropped column `amount`
select /* REMOVED:amount */ NULL from ecommerce.public.orders
```

### 2. `SAFE`
- Query: `select id, status from ecommerce.public.orders`
- Reason: Query does not reference `amount`
- Evidence: `urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`
