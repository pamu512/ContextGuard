# ContextGuard Breakage Certificate (`cgcert/v1`)

- **Run:** `6357b860-84ff-49c9-9d96-512052f5a9d7`
- **Issued:** 2026-07-25T23:44:00Z
- **Asset:** `ecommerce.public.orders` (`urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`)
- **Change:** `drop_column` amount
- **Risk:** CRITICAL (91)
- **Merge allowed:** NO
- **Hash:** `ba2035cf703eef86`

## Summary
- BREAKS: **3**
- SAFE: **1**
- UNKNOWN: **0**

## Query verdicts
### 1. `BREAKS`
- Query: `select o.amount, o.customer_email from ecommerce.public.orders o`
- Reason: Query references dropped column `amount`
- Evidence: `urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`
- Suggested patch:
```sql
-- Consumer patch: stop selecting dropped column `amount`
select o./*REMOVED*/NULL, o.customer_email from ecommerce.public.orders o
```

### 2. `BREAKS`
- Query: `select * from ecommerce.public.orders where status = 'complete'`
- Reason: Query uses SELECT * against `ecommerce.public.orders` — dropping `amount` changes the projection
- Evidence: `urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`
- Suggested patch:
```sql
-- Replace SELECT * with an explicit column list excluding `amount`
-- Suggested columns: customer_email, id, status
select * from ecommerce.public.orders where status = 'complete'
```

### 3. `SAFE`
- Query: `select id, status from ecommerce.public.orders`
- Reason: Query does not reference `amount`
- Evidence: `urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`

### 4. `BREAKS`
- Query: `select sum(amount) as gmv from ecommerce.public.orders`
- Reason: Query references dropped column `amount`
- Evidence: `urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.orders,PROD)`
- Suggested patch:
```sql
-- Consumer patch: stop selecting dropped column `amount`
select sum(/* REMOVED:amount */ NULL) as gmv from ecommerce.public.orders
```
