-- ContextGuard consumer patches (BREAKS only)

-- Patch 1: Query references dropped column `amount`
-- Consumer patch: stop selecting dropped column `amount`
select o./*REMOVED*/NULL, o.customer_email from ecommerce.public.orders o

-- Patch 2: Query uses SELECT * against `ecommerce.public.orders` — dropping `amount` changes the projection
-- Replace SELECT * with an explicit column list excluding `amount`
-- Suggested columns: customer_email, id, status
select * from ecommerce.public.orders where status = 'complete'

-- Patch 3: Query references dropped column `amount`
-- Consumer patch: stop selecting dropped column `amount`
select sum(/* REMOVED:amount */ NULL) as gmv from ecommerce.public.orders
