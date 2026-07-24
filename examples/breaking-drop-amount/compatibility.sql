-- Compatibility view preserving `amount` as NULL during migration
CREATE OR REPLACE VIEW ecommerce.public.orders_compat AS
SELECT * EXCLUDE (amount), CAST(NULL AS VARCHAR) AS amount
FROM ecommerce.public.orders;
