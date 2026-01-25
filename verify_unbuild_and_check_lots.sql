-- ============================================
-- VERIFY UNBUILD AND CHECK LOT AVAILABILITY
-- ============================================
-- This query verifies that lots have been properly restored
-- and are available for use in a new manufacturing order
--
-- Usage: Replace 'WH/MO/800188' with your unbuilt MO name
-- ============================================

-- ============================================
-- 1. VERIFY LOTS ARE RESTORED TO INVENTORY
-- ============================================
-- Check that lots are back in stock with correct quantities

SELECT 
    'Lots Restored' AS status,
    sl.id AS lot_id,
    sl.name AS lot_name,
    pt.name AS product_name,
    loc.complete_name AS location,
    sq.quantity AS available_quantity,
    sq.reserved_quantity AS reserved_quantity,
    (sq.quantity - sq.reserved_quantity) AS free_quantity,
    sq.in_date AS in_date
FROM stock_quant sq
INNER JOIN stock_lot sl ON sq.lot_id = sl.id
INNER JOIN product_product pp ON sq.product_id = pp.id
INNER JOIN product_template pt ON pp.product_tmpl_id = pt.id
INNER JOIN stock_location loc ON sq.location_id = loc.id
INNER JOIN stock_move_line sml ON sml.lot_id = sl.id
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE mo.name = 'WH/MO/800188'
  AND sm.location_id != sm.location_dest_id  -- Produce moves (restored lots)
  AND sml.qty_done > 0
  AND sq.quantity > 0  -- Only show lots with available quantity
ORDER BY sl.name, pt.name;

-- ============================================
-- 2. CHECK LOT AVAILABILITY FOR NEW MO
-- ============================================
-- Verify lots are in the correct locations and available

SELECT 
    'Lot Availability Check' AS status,
    sl.id AS lot_id,
    sl.name AS lot_name,
    pt.name AS product_name,
    loc.complete_name AS current_location,
    loc.usage AS location_usage,
    sq.quantity AS total_quantity,
    sq.reserved_quantity AS reserved_quantity,
    (sq.quantity - sq.reserved_quantity) AS available_for_mo,
    CASE 
        WHEN loc.usage = 'internal' AND sq.quantity > 0 THEN 'Available'
        WHEN loc.usage != 'internal' THEN 'Wrong Location Type'
        WHEN sq.quantity <= 0 THEN 'No Quantity'
        ELSE 'Check Required'
    END AS availability_status
FROM stock_quant sq
INNER JOIN stock_lot sl ON sq.lot_id = sl.id
INNER JOIN product_product pp ON sq.product_id = pp.id
INNER JOIN product_template pt ON pp.product_tmpl_id = pt.id
INNER JOIN stock_location loc ON sq.location_id = loc.id
INNER JOIN stock_move_line sml ON sml.lot_id = sl.id
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE mo.name = 'WH/MO/800188'
  AND sm.location_id != sm.location_dest_id
  AND sml.qty_done > 0
ORDER BY sl.name, pt.name;

-- ============================================
-- 3. SUMMARY: TOTAL QUANTITIES RESTORED
-- ============================================
-- Get a summary of what was restored

SELECT 
    pt.name AS product_name,
    COUNT(DISTINCT sl.id) AS number_of_lots,
    STRING_AGG(DISTINCT sl.name, ', ' ORDER BY sl.name) AS lot_names,
    SUM(sq.quantity) AS total_quantity_available,
    SUM(sq.reserved_quantity) AS total_reserved,
    SUM(sq.quantity - sq.reserved_quantity) AS total_free_quantity,
    STRING_AGG(DISTINCT loc.complete_name, ', ') AS locations
FROM stock_quant sq
INNER JOIN stock_lot sl ON sq.lot_id = sl.id
INNER JOIN product_product pp ON sq.product_id = pp.id
INNER JOIN product_template pt ON pp.product_tmpl_id = pt.id
INNER JOIN stock_location loc ON sq.location_id = loc.id
INNER JOIN stock_move_line sml ON sml.lot_id = sl.id
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE mo.name = 'WH/MO/800188'
  AND sm.location_id != sm.location_dest_id
  AND sml.qty_done > 0
  AND sq.quantity > 0
GROUP BY pt.name
ORDER BY pt.name;

-- ============================================
-- 4. CHECK FOR POTENTIAL ISSUES
-- ============================================
-- Identify any problems that might prevent using lots in new MO

SELECT 
    'Potential Issues' AS check_type,
    sl.name AS lot_name,
    pt.name AS product_name,
    loc.complete_name AS location,
    CASE 
        WHEN loc.usage != 'internal' THEN 'Location is not internal - lots may not be available for MO'
        WHEN sq.quantity <= 0 THEN 'No quantity available'
        WHEN sq.reserved_quantity >= sq.quantity THEN 'All quantity is reserved'
        WHEN sq.in_date IS NULL THEN 'Missing in_date'
        ELSE 'OK'
    END AS issue_description
FROM stock_quant sq
INNER JOIN stock_lot sl ON sq.lot_id = sl.id
INNER JOIN product_product pp ON sq.product_id = pp.id
INNER JOIN product_template pt ON pp.product_tmpl_id = pt.id
INNER JOIN stock_location loc ON sq.location_id = loc.id
INNER JOIN stock_move_line sml ON sml.lot_id = sl.id
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE mo.name = 'WH/MO/800188'
  AND sm.location_id != sm.location_dest_id
  AND sml.qty_done > 0
  AND (
      loc.usage != 'internal' 
      OR sq.quantity <= 0 
      OR sq.reserved_quantity >= sq.quantity
      OR sq.in_date IS NULL
  )
ORDER BY sl.name;
