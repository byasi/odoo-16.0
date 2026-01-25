-- ============================================
-- DIAGNOSE WHY TOTAL_PRODUCED_QTY IS 0.0
-- ============================================
-- This script investigates why finished moves show 0 quantity
-- Replace 'WH/MO/800188' with your MO name
-- ============================================

-- ============================================
-- STEP 1: Check Finished Moves
-- ============================================
SELECT 
    'Finished Moves' AS check_type,
    fm.id AS move_id,
    fm.name AS move_name,
    fm.product_id,
    fm.product_uom_qty AS move_planned_qty,
    fm.quantity_done AS move_quantity_done,
    fm.state AS move_state,
    fm.location_id,
    fm.location_dest_id,
    COUNT(sml.id) AS move_line_count,
    SUM(sml.qty_done) AS total_qty_done_in_lines,
    SUM(sml.reserved_uom_qty) AS total_reserved_in_lines
FROM mrp_production mo
INNER JOIN stock_move fm ON fm.production_id = mo.id
LEFT JOIN stock_move_line sml ON sml.move_id = fm.id
WHERE mo.name = 'WH/MO/800188'
  AND fm.product_id = mo.product_id
GROUP BY fm.id, fm.name, fm.product_id, fm.product_uom_qty, 
         fm.quantity_done, fm.state, fm.location_id, fm.location_dest_id
ORDER BY fm.id;

-- ============================================
-- STEP 2: Check All Finished Move Lines
-- ============================================
SELECT 
    'Finished Move Lines' AS check_type,
    sml.id AS move_line_id,
    sml.move_id,
    sml.product_id,
    sml.qty_done,
    sml.reserved_uom_qty,
    sml.lot_id,
    sl.name AS lot_name,
    sml.state AS line_state,
    sml.date AS line_date
FROM mrp_production mo
INNER JOIN stock_move fm ON fm.production_id = mo.id
INNER JOIN stock_move_line sml ON sml.move_id = fm.id
LEFT JOIN stock_lot sl ON sml.lot_id = sl.id
WHERE mo.name = 'WH/MO/800188'
  AND fm.product_id = mo.product_id
ORDER BY sml.id;

-- ============================================
-- STEP 3: Check if Finished Moves Exist
-- ============================================
SELECT 
    'Finished Moves Existence' AS check_type,
    COUNT(*) AS finished_move_count,
    COUNT(CASE WHEN fm.state = 'done' THEN 1 END) AS done_move_count,
    COUNT(CASE WHEN fm.quantity_done > 0 THEN 1 END) AS moves_with_quantity_done,
    COUNT(CASE WHEN sml.qty_done > 0 THEN 1 END) AS lines_with_qty_done
FROM mrp_production mo
LEFT JOIN stock_move fm ON fm.production_id = mo.id
    AND fm.product_id = mo.product_id
LEFT JOIN stock_move_line sml ON sml.move_id = fm.id
WHERE mo.name = 'WH/MO/800188';

-- ============================================
-- STEP 4: Check Raw Material Moves (for comparison)
-- ============================================
SELECT 
    'Raw Material Moves' AS check_type,
    COUNT(*) AS raw_move_count,
    COUNT(CASE WHEN rm.state = 'done' THEN 1 END) AS done_raw_move_count,
    SUM(rm.quantity_done) AS total_raw_quantity_done,
    SUM(rml.qty_done) AS total_raw_qty_done_in_lines
FROM mrp_production mo
LEFT JOIN stock_move rm ON rm.raw_material_production_id = mo.id
LEFT JOIN stock_move_line rml ON rml.move_id = rm.id
WHERE mo.name = 'WH/MO/800188';

-- ============================================
-- STEP 5: Calculate Produced Quantity from Move Lines
-- ============================================
SELECT 
    'Produced Qty Calculation' AS check_type,
    mo.product_qty AS mo_planned_qty,
    COALESCE(SUM(fm.quantity_done), 0) AS from_move_quantity_done,
    COALESCE(SUM(sml.qty_done), 0) AS from_move_lines_qty_done,
    CASE 
        WHEN COALESCE(SUM(sml.qty_done), 0) > 0 THEN COALESCE(SUM(sml.qty_done), 0)
        WHEN COALESCE(SUM(fm.quantity_done), 0) > 0 THEN COALESCE(SUM(fm.quantity_done), 0)
        ELSE mo.product_qty
    END AS calculated_unbuild_qty
FROM mrp_production mo
LEFT JOIN stock_move fm ON fm.production_id = mo.id
    AND fm.state = 'done'
    AND fm.product_id = mo.product_id
LEFT JOIN stock_move_line sml ON sml.move_id = fm.id
    AND sml.qty_done > 0
WHERE mo.name = 'WH/MO/800188'
GROUP BY mo.product_qty;

-- ============================================
-- STEP 6: Check Stock Quants for Finished Product
-- ============================================
SELECT 
    'Stock Quants' AS check_type,
    sq.product_id,
    sq.location_id,
    loc.name AS location_name,
    sq.quantity,
    sq.reserved_quantity,
    sq.lot_id,
    sl.name AS lot_name,
    sq.in_date
FROM mrp_production mo
INNER JOIN stock_quant sq ON sq.product_id = mo.product_id
INNER JOIN stock_location loc ON loc.id = sq.location_id
LEFT JOIN stock_lot sl ON sq.lot_id = sl.id
WHERE mo.name = 'WH/MO/800188'
  AND sq.location_id = mo.location_dest_id
ORDER BY sq.quantity DESC;
