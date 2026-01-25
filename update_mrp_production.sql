-- UPDATE query to modify product_id, product_uom_id, and state for mrp_production
-- Simply change the values below to update different records

-- First, verify the current data (optional - uncomment to use)
-- SELECT id, name, product_id, product_uom_id, state 
-- FROM mrp_production 
-- WHERE name = 'WH/MO/800179';

-- UPDATE query - Change the values as needed:
-- 1. Change 'WH/MO/800179' to the name of the mrp_production you want to update
-- 2. Change 123 to the desired product_id (from product_product table)
-- 3. Change 1 to the desired product_uom_id (from uom_uom table)
-- 4. Change 'to_close' to the desired state (see state values below)

UPDATE mrp_production
SET 
    product_id = 123,              -- Replace 123 with your desired product_id
    product_uom_id = 1,            -- Replace 1 with your desired product_uom_id
    state = 'to_close'             -- Replace 'to_close' with desired state (see options below)
WHERE 
    name = 'WH/MO/800179';        -- Replace 'WH/MO/800179' with the name you want to update

-- Verify the update (optional - uncomment to use)
-- SELECT id, name, product_id, product_uom_id, state 
-- FROM mrp_production 
-- WHERE name = 'WH/MO/800179';

-- ============================================
-- STATE VALUES: Available options for state field
-- ============================================
-- 'draft'      - Draft
-- 'confirmed'  - Confirmed
-- 'progress'   - In Progress
-- 'to_close'   - To Close
-- 'done'       - Done
-- 'cancel'     - Cancelled

-- ============================================
-- HELPER QUERIES: Use these to find the IDs you need
-- ============================================

-- Find product_id by product name or internal reference:
-- SELECT pp.id AS product_id, pt.name AS product_name, pp.default_code
-- FROM product_product pp
-- INNER JOIN product_template pt ON pp.product_tmpl_id = pt.id
-- WHERE pt.name ILIKE '%your_product_name%' 
--    OR pp.default_code ILIKE '%your_reference%';

-- Find product_uom_id by UOM name:
-- SELECT id AS uom_id, name AS uom_name
-- FROM uom_uom
-- WHERE name ILIKE '%Unit%'  -- or 'kg', 'm', 'L', etc.
-- ORDER BY name;
