-- ============================================
-- GET ALL LOTS USED IN A MANUFACTURING ORDER
-- ============================================
-- This query retrieves all lot/serial numbers that were consumed
-- to manufacture a specific manufacturing order.
--
-- Usage: Replace 'WH/MO/800188' with your manufacturing order name
-- ============================================

-- ============================================
-- MAIN QUERY: Get all lots with details
-- ============================================
SELECT 
    mo.id AS mo_id,
    mo.name AS manufacturing_order,
    mo.state AS mo_state,
    sm.id AS move_id,
    sm.state AS move_state,
    sm.product_id,
    pt.name AS product_name,
    pp.default_code AS product_code,
    sml.id AS move_line_id,
    sml.lot_id,
    sl.name AS lot_name,
    sl.ref AS lot_reference,
    sml.qty_done AS quantity_consumed,
    uom.name AS unit_of_measure,
    loc_from.complete_name AS from_location,
    loc_to.complete_name AS to_location,
    sml.date AS consumption_date
FROM 
    mrp_production mo
INNER JOIN 
    stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN 
    stock_move_line sml ON sml.move_id = sm.id
LEFT JOIN 
    stock_lot sl ON sml.lot_id = sl.id
LEFT JOIN 
    product_product pp ON sm.product_id = pp.id
LEFT JOIN 
    product_template pt ON pp.product_tmpl_id = pt.id
LEFT JOIN 
    uom_uom uom ON sml.product_uom_id = uom.id
LEFT JOIN 
    stock_location loc_from ON sml.location_id = loc_from.id
LEFT JOIN 
    stock_location loc_to ON sml.location_dest_id = loc_to.id
WHERE 
    mo.name = 'WH/MO/800188'  -- Replace with your manufacturing order name
    AND sml.lot_id IS NOT NULL  -- Only get lines with lot numbers
    AND sml.qty_done > 0  -- Only consumed quantities
ORDER BY 
    sl.name, sm.product_id, sml.id;

-- ============================================
-- SIMPLIFIED QUERY: Just lot IDs and names
-- ============================================
SELECT DISTINCT
    sl.id AS lot_id,
    sl.name AS lot_name,
    sl.ref AS lot_reference
FROM 
    mrp_production mo
INNER JOIN 
    stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN 
    stock_move_line sml ON sml.move_id = sm.id
INNER JOIN 
    stock_lot sl ON sml.lot_id = sl.id
WHERE 
    mo.name = 'WH/MO/800188'  -- Replace with your manufacturing order name
    AND sml.qty_done > 0
ORDER BY 
    sl.name;

-- ============================================
-- SUMMARY QUERY: Lots with quantities per product
-- ============================================
SELECT 
    mo.name AS manufacturing_order,
    pt.name AS product_name,
    sl.id AS lot_id,
    sl.name AS lot_name,
    SUM(sml.qty_done) AS total_quantity_consumed,
    uom.name AS unit_of_measure,
    COUNT(*) AS number_of_consumptions
FROM 
    mrp_production mo
INNER JOIN 
    stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN 
    stock_move_line sml ON sml.move_id = sm.id
LEFT JOIN 
    stock_lot sl ON sml.lot_id = sl.id
LEFT JOIN 
    product_product pp ON sm.product_id = pp.id
LEFT JOIN 
    product_template pt ON pp.product_tmpl_id = pt.id
LEFT JOIN 
    uom_uom uom ON sml.product_uom_id = uom.id
WHERE 
    mo.name = 'WH/MO/800188'  -- Replace with your manufacturing order name
    AND sml.lot_id IS NOT NULL
    AND sml.qty_done > 0
GROUP BY 
    mo.name, pt.name, sl.id, sl.name, uom.name
ORDER BY 
    pt.name, sl.name;

-- ============================================
-- COUNT QUERY: Total number of unique lots
-- ============================================
SELECT 
    mo.name AS manufacturing_order,
    COUNT(DISTINCT sml.lot_id) AS total_unique_lots,
    COUNT(sml.id) AS total_consumption_lines,
    SUM(sml.qty_done) AS total_quantity_consumed
FROM 
    mrp_production mo
INNER JOIN 
    stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN 
    stock_move_line sml ON sml.move_id = sm.id
WHERE 
    mo.name = 'WH/MO/800188'  -- Replace with your manufacturing order name
    AND sml.lot_id IS NOT NULL
    AND sml.qty_done > 0
GROUP BY 
    mo.name;

-- ============================================
-- PRODUCT-WISE BREAKDOWN: Lots per product
-- ============================================
SELECT 
    mo.name AS manufacturing_order,
    pt.name AS product_name,
    pp.default_code AS product_code,
    COUNT(DISTINCT sml.lot_id) AS number_of_lots,
    STRING_AGG(DISTINCT sl.name, ', ' ORDER BY sl.name) AS lot_names,
    SUM(sml.qty_done) AS total_quantity_consumed,
    uom.name AS unit_of_measure
FROM 
    mrp_production mo
INNER JOIN 
    stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN 
    stock_move_line sml ON sml.move_id = sm.id
LEFT JOIN 
    stock_lot sl ON sml.lot_id = sl.id
LEFT JOIN 
    product_product pp ON sm.product_id = pp.id
LEFT JOIN 
    product_template pt ON pp.product_tmpl_id = pt.id
LEFT JOIN 
    uom_uom uom ON sml.product_uom_id = uom.id
WHERE 
    mo.name = 'WH/MO/800188'  -- Replace with your manufacturing order name
    AND sml.lot_id IS NOT NULL
    AND sml.qty_done > 0
GROUP BY 
    mo.name, pt.name, pp.default_code, uom.name
ORDER BY 
    pt.name;

-- ============================================
-- EXPORT-FRIENDLY QUERY: CSV-ready format
-- ============================================
SELECT 
    mo.name AS "Manufacturing Order",
    sl.id AS "Lot ID",
    sl.name AS "Lot Name",
    pt.name AS "Product Name",
    pp.default_code AS "Product Code",
    sml.qty_done AS "Quantity Consumed",
    uom.name AS "Unit of Measure",
    loc_from.complete_name AS "From Location",
    loc_to.complete_name AS "To Location",
    sml.date::date AS "Consumption Date"
FROM 
    mrp_production mo
INNER JOIN 
    stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN 
    stock_move_line sml ON sml.move_id = sm.id
LEFT JOIN 
    stock_lot sl ON sml.lot_id = sl.id
LEFT JOIN 
    product_product pp ON sm.product_id = pp.id
LEFT JOIN 
    product_template pt ON pp.product_tmpl_id = pt.id
LEFT JOIN 
    uom_uom uom ON sml.product_uom_id = uom.id
LEFT JOIN 
    stock_location loc_from ON sml.location_id = loc_from.id
LEFT JOIN 
    stock_location loc_to ON sml.location_dest_id = loc_to.id
WHERE 
    mo.name = 'WH/MO/800188'  -- Replace with your manufacturing order name
    AND sml.lot_id IS NOT NULL
    AND sml.qty_done > 0
ORDER BY 
    sl.name, pt.name;
