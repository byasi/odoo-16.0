-- ============================================
-- UNDO LOT CONSUMPTION FROM MANUFACTURING ORDER
-- ============================================
-- This script helps reverse lot consumption when a manufacturing order
-- was confirmed by mistake and consumed lot numbers.
--
-- IMPORTANT: Backup your database before running these queries!
-- ============================================

-- ============================================
-- STEP 1: CHECK CURRENT STATE
-- ============================================
-- First, check the state of your manufacturing order and its stock moves
-- Replace 'WH/MO/800179' with your manufacturing order name

SELECT 
    mo.id AS mo_id,
    mo.name AS mo_name,
    mo.state AS mo_state,
    COUNT(DISTINCT sm.id) AS total_moves,
    COUNT(DISTINCT CASE WHEN sm.state = 'done' THEN sm.id END) AS done_moves,
    COUNT(DISTINCT CASE WHEN sm.state != 'done' AND sm.state != 'cancel' THEN sm.id END) AS active_moves,
    SUM(sml.qty_done) AS total_consumed_qty
FROM 
    mrp_production mo
LEFT JOIN 
    stock_move sm ON (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
LEFT JOIN 
    stock_move_line sml ON sml.move_id = sm.id
WHERE 
    mo.name = 'WH/MO/800179'  -- Replace with your MO name
GROUP BY 
    mo.id, mo.name, mo.state;

-- ============================================
-- STEP 2: VIEW CONSUMED LOTS
-- ============================================
-- See all the lot numbers that were consumed
-- Replace 'WH/MO/800179' with your manufacturing order name

SELECT 
    mo.name AS mo_name,
    sm.id AS move_id,
    sm.state AS move_state,
    sm.product_id,
    pt.name AS product_name,
    sml.id AS move_line_id,
    sml.lot_id,
    sl.name AS lot_name,
    sml.qty_done AS consumed_qty,
    sml.location_id,
    loc_from.complete_name AS from_location,
    sml.location_dest_id,
    loc_to.complete_name AS to_location
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
    stock_location loc_from ON sml.location_id = loc_from.id
LEFT JOIN 
    stock_location loc_to ON sml.location_dest_id = loc_to.id
WHERE 
    mo.name = 'WH/MO/800179'  -- Replace with your MO name
    AND sml.qty_done > 0
ORDER BY 
    sml.lot_id, sm.id;

-- ============================================
-- SCENARIO A: MOVES ARE NOT YET 'DONE'
-- ============================================
-- If stock moves are in states: 'draft', 'waiting', 'confirmed', 'assigned'
-- You can cancel the manufacturing order and moves will be cancelled

-- Option A1: Cancel the Manufacturing Order (via Odoo UI or Python)
-- This is the safest method. In Odoo, go to the MO and click "Cancel"
-- Or use this SQL to set state to cancel (if moves are not done):

-- WARNING: Only use this if moves are NOT in 'done' state!
-- First verify with STEP 1 query above

UPDATE mrp_production
SET state = 'cancel'
WHERE name = 'WH/MO/800179'  -- Replace with your MO name
  AND id NOT IN (
      -- Only cancel if there are no done moves
      SELECT DISTINCT mo.id
      FROM mrp_production mo
      INNER JOIN stock_move sm ON (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
      WHERE mo.name = 'WH/MO/800179'
        AND sm.state = 'done'
  );

-- Cancel associated stock moves (only if not done)
UPDATE stock_move
SET state = 'cancel'
WHERE (raw_material_production_id IN (
    SELECT id FROM mrp_production WHERE name = 'WH/MO/800179'
) OR production_id IN (
    SELECT id FROM mrp_production WHERE name = 'WH/MO/800179'
))
AND state != 'done'
AND state != 'cancel';

-- ============================================
-- SCENARIO B: MOVES ARE ALREADY 'DONE'
-- ============================================
-- If stock moves are in 'done' state, you need to reverse them
-- This is more complex and requires creating reverse moves

-- Option B1: Reset qty_done to 0 in stock_move_line (reverses consumption)
-- This will restore the lots back to their original location
-- WARNING: This is a direct database manipulation - use with caution!

-- First, create a backup view of what will be changed:
CREATE OR REPLACE VIEW mrp_consumption_backup AS
SELECT 
    sml.id AS move_line_id,
    sml.move_id,
    sml.lot_id,
    sml.product_id,
    sml.qty_done,
    sml.location_id,
    sml.location_dest_id,
    sm.state AS move_state,
    mo.name AS mo_name
FROM 
    stock_move_line sml
INNER JOIN 
    stock_move sm ON sml.move_id = sm.id
INNER JOIN 
    mrp_production mo ON (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
WHERE 
    mo.name = 'WH/MO/800179'  -- Replace with your MO name
    AND sml.qty_done > 0;

-- View the backup before making changes:
-- SELECT * FROM mrp_consumption_backup;

-- Reset qty_done to 0 (this reverses the consumption)
-- WARNING: This will restore inventory but may cause accounting issues
-- Consider using Odoo's built-in reversal methods instead
UPDATE stock_move_line sml
SET qty_done = 0
FROM stock_move sm, mrp_production mo
WHERE sml.move_id = sm.id
  AND (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
  AND mo.name = 'WH/MO/800179'  -- Replace with your MO name
  AND sml.qty_done > 0
  AND sm.state = 'done';

-- Option B2: Update stock quants to restore inventory
-- This directly updates the inventory quantities
-- WARNING: This bypasses Odoo's normal inventory flow!

-- First, see what quants will be affected:
SELECT 
    sq.id AS quant_id,
    sq.product_id,
    sq.lot_id,
    sq.location_id,
    sq.quantity AS current_quantity,
    sml.qty_done AS consumed_qty,
    loc.complete_name AS location_name
FROM 
    stock_quant sq
INNER JOIN 
    stock_move_line sml ON sq.lot_id = sml.lot_id AND sq.product_id = sml.product_id
INNER JOIN 
    stock_move sm ON sml.move_id = sm.id
INNER JOIN 
    mrp_production mo ON (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
WHERE 
    mo.name = 'WH/MO/800179'  -- Replace with your MO name
    AND sml.qty_done > 0
    AND sm.state = 'done'
    AND sq.location_id = sml.location_dest_id;  -- Where the lot was moved to

-- Restore quantities in source location (where lots came from)
-- This adds back the consumed quantity to the original location
UPDATE stock_quant sq
SET quantity = quantity + sml.qty_done
FROM stock_move_line sml, stock_move sm, mrp_production mo
WHERE sq.lot_id = sml.lot_id 
  AND sq.product_id = sml.product_id
  AND sq.location_id = sml.location_id  -- Original source location
  AND sml.move_id = sm.id
  AND (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
  AND mo.name = 'WH/MO/800179'  -- Replace with your MO name
  AND sml.qty_done > 0
  AND sm.state = 'done';

-- Remove quantities from destination location (where lots were consumed)
UPDATE stock_quant sq
SET quantity = quantity - sml.qty_done
FROM stock_move_line sml, stock_move sm, mrp_production mo
WHERE sq.lot_id = sml.lot_id 
  AND sq.product_id = sml.product_id
  AND sq.location_id = sml.location_dest_id  -- Destination location
  AND sml.move_id = sm.id
  AND (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
  AND mo.name = 'WH/MO/800179'  -- Replace with your MO name
  AND sml.qty_done > 0
  AND sm.state = 'done'
  AND sq.quantity >= sml.qty_done;  -- Safety check

-- ============================================
-- RECOMMENDED APPROACH: Use Odoo's Built-in Methods
-- ============================================
-- The safest way is to use Odoo's Python API:
--
-- 1. If MO is not done and moves are not done:
--    - Cancel the MO via UI or: mo.action_cancel()
--
-- 2. If moves are done, create reverse moves:
--    - Use stock.move._reverse_moves() method
--    - Or create manual inventory adjustments
--
-- 3. For accounting accuracy, use proper reversal methods
--    that handle COGS, valuation layers, etc.

-- ============================================
-- VERIFICATION QUERIES
-- ============================================
-- After making changes, verify the results:

-- Check MO state
SELECT id, name, state FROM mrp_production WHERE name = 'WH/MO/800179';

-- Check move states
SELECT 
    sm.id, 
    sm.state, 
    sm.product_id,
    pt.name AS product_name,
    COUNT(sml.id) AS move_lines,
    SUM(sml.qty_done) AS total_qty_done
FROM stock_move sm
LEFT JOIN stock_move_line sml ON sml.move_id = sm.id
LEFT JOIN product_product pp ON sm.product_id = pp.id
LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
WHERE (sm.raw_material_production_id IN (
    SELECT id FROM mrp_production WHERE name = 'WH/MO/800179'
) OR sm.production_id IN (
    SELECT id FROM mrp_production WHERE name = 'WH/MO/800179'
))
GROUP BY sm.id, sm.state, sm.product_id, pt.name;

-- Check lot quantities restored
SELECT 
    sl.name AS lot_name,
    sq.location_id,
    loc.complete_name AS location,
    sq.quantity
FROM stock_quant sq
INNER JOIN stock_lot sl ON sq.lot_id = sl.id
INNER JOIN stock_location loc ON sq.location_id = loc.id
WHERE sq.lot_id IN (
    SELECT DISTINCT sml.lot_id
    FROM stock_move_line sml
    INNER JOIN stock_move sm ON sml.move_id = sm.id
    INNER JOIN mrp_production mo ON (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
    WHERE mo.name = 'WH/MO/800179'
)
ORDER BY sl.name, loc.complete_name;
