-- Soft type migration via casted compatibility column
CREATE OR REPLACE VIEW ecommerce.public.orders_compat AS
SELECT * EXCLUDE (status), CAST(status AS VARCHAR) AS status
FROM ecommerce.public.orders;
