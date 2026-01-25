-- SQL Query to get all products and their names from Odoo database
-- This query joins product_product with product_template to get product names

SELECT 
    pp.id AS product_id,
    pt.name AS product_name,
    pp.default_code AS internal_reference,
    pp.active AS is_active
FROM 
    product_product pp
INNER JOIN 
    product_template pt ON pp.product_tmpl_id = pt.id
ORDER BY 
    pt.name;

-- Alternative: Get only active products
-- SELECT 
--     pp.id AS product_id,
--     pt.name AS product_name,
--     pp.default_code AS internal_reference
-- FROM 
--     product_product pp
-- INNER JOIN 
--     product_template pt ON pp.product_tmpl_id = pt.id
-- WHERE 
--     pp.active = true
-- ORDER BY 
--     pt.name;

-- Simple version: Just product ID and name
-- SELECT 
--     pp.id AS product_id,
--     pt.name AS product_name
-- FROM 
--     product_product pp
-- INNER JOIN 
--     product_template pt ON pp.product_tmpl_id = pt.id
-- ORDER BY 
--     pt.name;
