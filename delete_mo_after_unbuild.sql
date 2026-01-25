-- ============================================
-- SAFE DELETION OF MANUFACTURING ORDER AFTER UNBUILD
-- ============================================
-- This script safely deletes a manufacturing order after unbuild is complete.
-- It handles all dependencies and ensures data integrity.
--
-- WARNING: Backup your database before running!
-- 
-- Usage: Replace 'WH/MO/800188' with your manufacturing order name
-- ============================================

-- ============================================
-- STEP 1: VERIFY UNBUILD IS COMPLETE
-- ============================================
-- Check that unbuild exists and is done

SELECT 
    'Unbuild Status' AS check_type,
    ub.id AS unbuild_id,
    ub.name AS unbuild_name,
    ub.state AS unbuild_state,
    mo.id AS mo_id,
    mo.name AS mo_name,
    mo.state AS mo_state,
    COUNT(DISTINCT sm.id) AS unbuild_moves_created
FROM mrp_production mo
LEFT JOIN mrp_unbuild ub ON ub.mo_id = mo.id
LEFT JOIN stock_move sm ON sm.unbuild_id = ub.id
WHERE mo.name = 'WH/MO/800188'
GROUP BY ub.id, ub.name, ub.state, mo.id, mo.name, mo.state;

-- ============================================
-- STEP 2: CHECK DEPENDENCIES
-- ============================================
-- Verify what will be affected by deletion

SELECT 
    'Dependency Check' AS check_type,
    'Stock Moves (Original MO)' AS entity_type,
    COUNT(*) AS count,
    STRING_AGG(DISTINCT sm.state::text, ', ') AS states
FROM mrp_production mo
INNER JOIN stock_move sm ON (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
WHERE mo.name = 'WH/MO/800188'

UNION ALL

SELECT 
    'Dependency Check',
    'Unbuild Moves',
    COUNT(*),
    STRING_AGG(DISTINCT sm.state::text, ', ')
FROM mrp_production mo
INNER JOIN mrp_unbuild ub ON ub.mo_id = mo.id
INNER JOIN stock_move sm ON sm.unbuild_id = ub.id
WHERE mo.name = 'WH/MO/800188'

UNION ALL

SELECT 
    'Dependency Check',
    'Work Orders',
    COUNT(*),
    STRING_AGG(DISTINCT wo.state::text, ', ')
FROM mrp_production mo
INNER JOIN mrp_workorder wo ON wo.production_id = mo.id
WHERE mo.name = 'WH/MO/800188';

-- ============================================
-- STEP 3: VERIFY LOTS ARE RESTORED
-- ============================================
-- Make sure lots are back in inventory before deleting MO

SELECT 
    'Lots Restored Check' AS check_type,
    COUNT(DISTINCT sl.id) AS total_lots_restored,
    COUNT(DISTINCT CASE WHEN sq.quantity > 0 THEN sl.id END) AS lots_with_quantity,
    SUM(sq.quantity) AS total_quantity_restored
FROM mrp_production mo
INNER JOIN mrp_unbuild ub ON ub.mo_id = mo.id
INNER JOIN stock_move sm ON sm.unbuild_id = ub.id
INNER JOIN stock_move_line sml ON sml.move_id = sm.id
INNER JOIN stock_lot sl ON sml.lot_id = sl.id
INNER JOIN stock_quant sq ON sq.lot_id = sl.id
WHERE mo.name = 'WH/MO/800188'
  AND sm.location_id != sm.location_dest_id  -- Produce moves
  AND sml.qty_done > 0;

-- ============================================
-- STEP 4: CLEAN UP UNBUILD MOVES REFERENCES
-- ============================================
-- Remove references from unbuild moves to original MO moves
-- This allows safe deletion of the MO

-- Update unbuild moves to remove origin_returned_move_id references
-- (Optional - keeps audit trail but allows MO deletion)
UPDATE stock_move sm
SET origin_returned_move_id = NULL
FROM mrp_unbuild ub
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE sm.unbuild_id = ub.id
  AND mo.name = 'WH/MO/800188'
  AND sm.origin_returned_move_id IS NOT NULL;

-- ============================================
-- STEP 5: DELETE WORK ORDERS
-- ============================================
-- Delete work orders associated with the MO

DELETE FROM mrp_workorder
WHERE production_id IN (
    SELECT id FROM mrp_production WHERE name = 'WH/MO/800188'
);

-- ============================================
-- STEP 6: CANCEL/REMOVE ORIGINAL MO STOCK MOVES
-- ============================================
-- The original MO moves are already 'done', but we need to handle them
-- Option A: Keep them for audit trail (recommended)
-- Option B: Cancel them if not done (only if not done)

-- Cancel any non-done moves
UPDATE stock_move
SET state = 'cancel'
WHERE (raw_material_production_id IN (
    SELECT id FROM mrp_production WHERE name = 'WH/MO/800188'
) OR production_id IN (
    SELECT id FROM mrp_production WHERE name = 'WH/MO/800188'
))
AND state != 'done'
AND state != 'cancel';

-- Note: We keep 'done' moves for audit trail
-- If you want to delete them too, uncomment below (NOT RECOMMENDED):
-- DELETE FROM stock_move_line
-- WHERE move_id IN (
--     SELECT id FROM stock_move 
--     WHERE (raw_material_production_id IN (
--         SELECT id FROM mrp_production WHERE name = 'WH/MO/800188'
--     ) OR production_id IN (
--         SELECT id FROM mrp_production WHERE name = 'WH/MO/800188'
--     ))
--     AND state = 'done'
-- );
-- 
-- DELETE FROM stock_move
-- WHERE (raw_material_production_id IN (
--     SELECT id FROM mrp_production WHERE name = 'WH/MO/800188'
-- ) OR production_id IN (
--     SELECT id FROM mrp_production WHERE name = 'WH/MO/800188'
-- ))
-- AND state = 'done';

-- ============================================
-- STEP 7: DELETE THE MANUFACTURING ORDER
-- ============================================
-- Since MO is in 'done' state, we need to bypass Odoo's constraint
-- First, set state to 'cancel' to allow deletion

-- Set MO to cancel state (bypasses done state constraint)
UPDATE mrp_production
SET state = 'cancel'
WHERE name = 'WH/MO/800188'
  AND state = 'done';

-- Now delete the MO
DELETE FROM mrp_production
WHERE name = 'WH/MO/800188';

-- ============================================
-- STEP 8: VERIFY DELETION
-- ============================================
-- Confirm MO is deleted but unbuild and lots remain

-- Check MO is deleted
SELECT 
    'MO Deletion Check' AS status,
    COUNT(*) AS mo_count
FROM mrp_production
WHERE name = 'WH/MO/800188';

-- Check unbuild still exists
SELECT 
    'Unbuild Status' AS status,
    ub.id,
    ub.name,
    ub.state,
    ub.mo_id  -- Should be NULL or point to deleted MO
FROM mrp_unbuild ub
WHERE ub.name LIKE 'UNBUILD/WH/MO/800188%'
ORDER BY ub.id DESC
LIMIT 1;

-- Check lots are still in inventory
SELECT 
    'Lots Still Available' AS status,
    COUNT(DISTINCT sl.id) AS lots_count,
    SUM(sq.quantity) AS total_quantity
FROM stock_quant sq
INNER JOIN stock_lot sl ON sq.lot_id = sl.id
INNER JOIN stock_move_line sml ON sml.lot_id = sl.id
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
WHERE ub.name LIKE 'UNBUILD/WH/MO/800188%'
  AND sq.quantity > 0;

-- ============================================
-- OPTIONAL: CLEAN UP UNBUILD ORDER
-- ============================================
-- You can optionally delete the unbuild order too, but it's recommended
-- to keep it for audit trail. Uncomment if you want to delete it:

-- DELETE FROM stock_move_line
-- WHERE move_id IN (
--     SELECT id FROM stock_move WHERE unbuild_id IN (
--         SELECT id FROM mrp_unbuild WHERE name LIKE 'UNBUILD/WH/MO/800188%'
--     )
-- );
-- 
-- DELETE FROM stock_move
-- WHERE unbuild_id IN (
--     SELECT id FROM mrp_unbuild WHERE name LIKE 'UNBUILD/WH/MO/800188%'
-- );
-- 
-- DELETE FROM mrp_unbuild
-- WHERE name LIKE 'UNBUILD/WH/MO/800188%';
