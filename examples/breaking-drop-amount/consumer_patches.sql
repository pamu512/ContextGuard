-- ContextGuard consumer patches (BREAKS only)

-- Patch 1: Query references dropped column `amount`
-- Consumer patch: stop selecting dropped column `amount`
select /* REMOVED:amount */ NULL from ecommerce.public.orders
