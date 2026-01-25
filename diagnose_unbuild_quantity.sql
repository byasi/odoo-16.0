-- ============================================
-- DIAGNOSE UNBUILD QUANTITY ISSUE
-- ============================================
-- This script helps identify why unbuild quantity is 0.00
-- and what quantity should actually be used
-- ============================================

-- Replace 'WH/MO/800188' with your MO name
-- Replace 'UNBUILD/WH/MO/800188' with your unbuild name if different

-- ============================================
-- STEP 1: Check Manufacturing Order Details
-- ============================================
SELECT 
    'MO Details' AS check_type,
    mo.id AS mo_id,
    mo.name AS mo_name,
    mo.state AS mo_state,
    mo.product_id,
    mo.product_qty AS mo_product_qty,
    mo.qty_producing AS mo_qty_producing
FROM mrp_production mo
WHERE mo.name = 'WH/MO/800188';

-- ============================================
-- STEP 2: Check Finished Moves (What was produced)
-- ============================================
SELECT 
    'Finished Moves' AS check_type,
    fm.id AS move_id,
    fm.name AS move_name,
    fm.product_id,
    fm.product_uom_qty,
    fm.quantity_done,
    fm.state,
    fm.location_id,
    fm.location_dest_id,
    COUNT(sml.id) AS move_line_count,
    SUM(sml.qty_done) AS total_qty_done_in_lines
FROM mrp_production mo
INNER JOIN stock_move fm ON fm.production_id = mo.id
LEFT JOIN stock_move_line sml ON sml.move_id = fm.id
WHERE mo.name = 'WH/MO/800188'
  AND fm.product_id = mo.product_id
  AND fm.state = 'done'
GROUP BY fm.id, fm.name, fm.product_id, fm.product_uom_qty, 
         fm.quantity_done, fm.state, fm.location_id, fm.location_dest_id;

-- ============================================
-- STEP 3: Check Available Quantity in Stock
-- ============================================
-- This is what Odoo checks before allowing unbuild
SELECT 
    'Available Stock' AS check_type,
    mo.product_id,
    mo.location_dest_id AS stock_location_id,
    loc.name AS stock_location_name,
    COALESCE(SUM(sq.quantity), 0) AS available_quantity,
    COUNT(DISTINCT sq.lot_id) AS lots_count
FROM mrp_production mo
INNER JOIN stock_location loc ON loc.id = mo.location_dest_id
LEFT JOIN stock_quant sq ON sq.product_id = mo.product_id 
    AND sq.location_id = mo.location_dest_id
WHERE mo.name = 'WH/MO/800188'
GROUP BY mo.product_id, mo.location_dest_id, loc.name;

-- ============================================
-- STEP 4: Check Unbuild Order Details
-- ============================================
SELECT 
    'Unbuild Order' AS check_type,
    ub.id AS unbuild_id,
    ub.name AS unbuild_name,
    ub.state AS unbuild_state,
    ub.product_id,
    ub.product_qty AS unbuild_product_qty,
    ub.mo_id,
    ub.location_id AS source_location_id,
    ub.location_dest_id AS dest_location_id
FROM mrp_unbuild ub
WHERE ub.mo_id = (SELECT id FROM mrp_production WHERE name = 'WH/MO/800188')
   OR ub.name LIKE 'UNBUILD/WH/MO/800188%'
ORDER BY ub.id DESC;

-- ============================================
-- STEP 5: Check Unbuild Moves (Consume moves for finished product)
-- ============================================
SELECT 
    'Unbuild Consume Moves' AS check_type,
    sm.id AS move_id,
    sm.name AS move_name,
    sm.product_id,
    sm.product_uom_qty,
    sm.quantity_done,
    sm.state,
    sm.location_id,
    sm.location_dest_id,
    COUNT(sml.id) AS move_line_count,
    SUM(sml.qty_done) AS total_qty_done_in_lines
FROM mrp_unbuild ub
INNER JOIN stock_move sm ON sm.unbuild_id = ub.id
LEFT JOIN stock_move_line sml ON sml.move_id = sm.id
WHERE ub.mo_id = (SELECT id FROM mrp_production WHERE name = 'WH/MO/800188')
   OR ub.name LIKE 'UNBUILD/WH/MO/800188%'
GROUP BY sm.id, sm.name, sm.product_id, sm.product_uom_qty, 
         sm.quantity_done, sm.state, sm.location_id, sm.location_dest_id
ORDER BY sm.id DESC;

-- ============================================
-- STEP 6: Compare Quantities
-- ============================================
SELECT 
    'Quantity Comparison' AS check_type,
    mo.product_qty AS mo_planned_qty,
    COALESCE(SUM(fm.quantity_done), 0) AS total_produced_qty,
    COALESCE(SUM(sq.quantity), 0) AS available_in_stock,
    ub.product_qty AS unbuild_qty,
    COALESCE(SUM(ub_sm.quantity_done), 0) AS unbuild_consumed_qty
FROM mrp_production mo
LEFT JOIN stock_move fm ON fm.production_id = mo.id 
    AND fm.state = 'done' 
    AND fm.product_id = mo.product_id
LEFT JOIN stock_quant sq ON sq.product_id = mo.product_id 
    AND sq.location_id = mo.location_dest_id
LEFT JOIN mrp_unbuild ub ON ub.mo_id = mo.id
LEFT JOIN stock_move ub_sm ON ub_sm.unbuild_id = ub.id
    AND ub_sm.location_id = mo.location_dest_id  -- Consume moves
WHERE mo.name = 'WH/MO/800188'
GROUP BY mo.product_qty, ub.product_qty;
