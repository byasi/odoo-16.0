-- ============================================
-- COMPLETE DELETION OF MANUFACTURING ORDER
-- AND RESET OF RELATED PURCHASE ORDERS
-- ============================================
-- 
-- WARNING: THIS IS A DANGEROUS OPERATION!
-- - This will delete manufacturing orders, lots, stock moves, and accounting entries
-- - This will reset purchase orders to allow re-receiving
-- - BACKUP YOUR DATABASE BEFORE RUNNING!
-- 
-- Usage: Replace 'WH/MO/800188' with your manufacturing order name
-- ============================================

-- ============================================
-- STEP 1: DIAGNOSTICS - Check what will be affected
-- ============================================
-- Run this first to see what will be deleted

SELECT 
    'Manufacturing Order' AS entity_type,
    mo.id AS entity_id,
    mo.name AS entity_name,
    mo.state AS state
FROM mrp_production mo
WHERE mo.name = 'WH/MO/800188'

UNION ALL

SELECT 
    'Stock Move (Raw Materials)' AS entity_type,
    sm.id AS entity_id,
    sm.name AS entity_name,
    sm.state AS state
FROM mrp_production mo
INNER JOIN stock_move sm ON sm.raw_material_production_id = mo.id
WHERE mo.name = 'WH/MO/800188'

UNION ALL

SELECT 
    'Stock Move (Finished)' AS entity_type,
    sm.id AS entity_id,
    sm.name AS entity_name,
    sm.state AS state
FROM mrp_production mo
INNER JOIN stock_move sm ON sm.production_id = mo.id
WHERE mo.name = 'WH/MO/800188'

UNION ALL

SELECT 
    'Stock Move Line' AS entity_type,
    sml.id AS entity_id,
    CONCAT('Line for lot: ', COALESCE(sl.name, 'No lot')) AS entity_name,
    sml.state AS state
FROM mrp_production mo
INNER JOIN stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN stock_move_line sml ON sml.move_id = sm.id
LEFT JOIN stock_lot sl ON sml.lot_id = sl.id
WHERE mo.name = 'WH/MO/800188'

UNION ALL

SELECT 
    'Lot Number' AS entity_type,
    sl.id AS entity_id,
    sl.name AS entity_name,
    'N/A' AS state
FROM mrp_production mo
INNER JOIN stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN stock_move_line sml ON sml.move_id = sm.id
INNER JOIN stock_lot sl ON sml.lot_id = sl.id
WHERE mo.name = 'WH/MO/800188'
  AND sml.qty_done > 0

UNION ALL

SELECT 
    'Purchase Order' AS entity_type,
    po.id AS entity_id,
    po.name AS entity_name,
    po.state AS state
FROM mrp_production mo
INNER JOIN stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN stock_move_line sml ON sml.move_id = sm.id
INNER JOIN stock_lot sl ON sml.lot_id = sl.id
INNER JOIN stock_move_line po_sml ON po_sml.lot_id = sl.id
INNER JOIN stock_move po_sm ON po_sml.move_id = po_sm.id
INNER JOIN stock_location po_loc ON po_sm.location_id = po_loc.id
INNER JOIN purchase_order_line pol ON po_sm.purchase_line_id = pol.id
INNER JOIN purchase_order po ON pol.order_id = po.id
WHERE mo.name = 'WH/MO/800188'
  AND sml.qty_done > 0
  AND po_loc.usage = 'supplier'  -- Incoming moves from supplier
GROUP BY po.id, po.name, po.state

UNION ALL

SELECT 
    'Stock Picking (Purchase Receipt)' AS entity_type,
    picking.id AS entity_id,
    picking.name AS entity_name,
    picking.state AS state
FROM mrp_production mo
INNER JOIN stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN stock_move_line sml ON sml.move_id = sm.id
INNER JOIN stock_lot sl ON sml.lot_id = sl.id
INNER JOIN stock_move_line po_sml ON po_sml.lot_id = sl.id
INNER JOIN stock_move po_sm ON po_sml.move_id = po_sm.id
INNER JOIN stock_picking picking ON po_sm.picking_id = picking.id
WHERE mo.name = 'WH/MO/800188'
  AND sml.qty_done > 0
  AND po_sm.location_id.usage = 'supplier'
GROUP BY picking.id, picking.name, picking.state

UNION ALL

SELECT 
    'Account Move (Stock Valuation)' AS entity_type,
    am.id AS entity_id,
    am.name AS entity_name,
    am.state AS state
FROM mrp_production mo
INNER JOIN stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN account_move_line aml ON aml.stock_move_id = sm.id
INNER JOIN account_move am ON aml.move_id = am.id
WHERE mo.name = 'WH/MO/800188'
GROUP BY am.id, am.name, am.state;

-- ============================================
-- STEP 2: Find all lots and their source purchase orders
-- ============================================

SELECT DISTINCT
    mo.name AS manufacturing_order,
    sl.id AS lot_id,
    sl.name AS lot_name,
    po.id AS purchase_order_id,
    po.name AS purchase_order_name,
    po.state AS po_state,
    picking.id AS picking_id,
    picking.name AS picking_name,
    picking.state AS picking_state,
    pol.id AS purchase_line_id,
    pol.product_id,
    pt.name AS product_name,
    pol.qty_received AS qty_received
FROM 
    mrp_production mo
INNER JOIN 
    stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN 
    stock_move_line sml ON sml.move_id = sm.id
INNER JOIN 
    stock_lot sl ON sml.lot_id = sl.id
-- Find purchase order moves that created these lots
INNER JOIN 
    stock_move_line po_sml ON po_sml.lot_id = sl.id
INNER JOIN 
    stock_move po_sm ON po_sml.move_id = po_sm.id
INNER JOIN 
    stock_location po_loc ON po_sm.location_id = po_loc.id
INNER JOIN 
    stock_picking picking ON po_sm.picking_id = picking.id
INNER JOIN 
    purchase_order_line pol ON po_sm.purchase_line_id = pol.id
INNER JOIN 
    purchase_order po ON pol.order_id = po.id
LEFT JOIN 
    product_product pp ON po_sm.product_id = pp.id
LEFT JOIN 
    product_template pt ON pp.product_tmpl_id = pt.id
WHERE 
    mo.name = 'WH/MO/800188'
    AND sml.qty_done > 0
    AND po_loc.usage = 'supplier'  -- Incoming from supplier
ORDER BY 
    po.name, sl.name;

-- ============================================
-- STEP 3: REVERSE STOCK MOVES AND ACCOUNTING
-- ============================================
-- This must be done BEFORE deleting the MO

-- 3.1: Cancel/Reverse stock moves from manufacturing order
-- First, cancel moves that are not done
UPDATE stock_move
SET state = 'cancel'
WHERE (raw_material_production_id IN (
    SELECT id FROM mrp_production WHERE name = 'WH/MO/800188'
) OR production_id IN (
    SELECT id FROM mrp_production WHERE name = 'WH/MO/800188'
))
AND state != 'done'
AND state != 'cancel';

-- 3.2: For done moves, we need to reverse them
-- This is complex - we'll reset qty_done first, then handle accounting

-- Reset qty_done in move lines (reverses consumption)
UPDATE stock_move_line sml
SET qty_done = 0
FROM stock_move sm, mrp_production mo
WHERE sml.move_id = sm.id
  AND (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
  AND mo.name = 'WH/MO/800188'
  AND sml.qty_done > 0;

-- ============================================
-- STEP 4: REVERSE STOCK QUANTS (Restore inventory)
-- ============================================

-- 4.1: Restore quantities in source locations (where lots came from)
UPDATE stock_quant sq
SET quantity = quantity + sml.qty_done
FROM stock_move_line sml, stock_move sm, mrp_production mo
WHERE sq.lot_id = sml.lot_id 
  AND sq.product_id = sml.product_id
  AND sq.location_id = sml.location_id  -- Original source location
  AND sml.move_id = sm.id
  AND (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
  AND mo.name = 'WH/MO/800188'
  AND sml.qty_done > 0
  AND sm.state = 'done';

-- 4.2: Remove quantities from destination locations (where lots were consumed)
UPDATE stock_quant sq
SET quantity = GREATEST(0, quantity - sml.qty_done)  -- Prevent negative
FROM stock_move_line sml, stock_move sm, mrp_production mo
WHERE sq.lot_id = sml.lot_id 
  AND sq.product_id = sml.product_id
  AND sq.location_id = sml.location_dest_id  -- Destination location
  AND sml.move_id = sm.id
  AND (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
  AND mo.name = 'WH/MO/800188'
  AND sml.qty_done > 0
  AND sm.state = 'done'
  AND sq.quantity >= sml.qty_done;

-- ============================================
-- STEP 5: DELETE LOT NUMBERS
-- ============================================
-- WARNING: Only delete lots that were ONLY used in this MO
-- If lots are used elsewhere, DO NOT DELETE them!

-- First, identify lots that are ONLY used in this MO
CREATE TEMP TABLE mo_only_lots AS
SELECT DISTINCT sl.id AS lot_id
FROM mrp_production mo
INNER JOIN stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN stock_move_line sml ON sml.move_id = sm.id
INNER JOIN stock_lot sl ON sml.lot_id = sl.id
WHERE mo.name = 'WH/MO/800188'
  AND sml.qty_done > 0
  AND sl.id NOT IN (
      -- Exclude lots used in other MOs
      SELECT DISTINCT sml2.lot_id
      FROM stock_move_line sml2
      INNER JOIN stock_move sm2 ON sml2.move_id = sm2.id
      WHERE sm2.raw_material_production_id NOT IN (
          SELECT id FROM mrp_production WHERE name = 'WH/MO/800188'
      )
      AND sml2.lot_id IS NOT NULL
  );

-- Delete move lines associated with these lots (from MO)
DELETE FROM stock_move_line sml
USING stock_move sm, mrp_production mo
WHERE sml.move_id = sm.id
  AND (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
  AND mo.name = 'WH/MO/800188'
  AND sml.lot_id IN (SELECT lot_id FROM mo_only_lots);

-- Delete the lots themselves
DELETE FROM stock_lot
WHERE id IN (SELECT lot_id FROM mo_only_lots);

-- Clean up temp table
DROP TABLE IF EXISTS mo_only_lots;

-- ============================================
-- STEP 6: RESET PURCHASE ORDERS
-- ============================================
-- This allows re-receiving products to create new lots

-- 6.1: Cancel purchase order pickings (receipts)
UPDATE stock_picking picking
SET state = 'cancel'
FROM mrp_production mo
INNER JOIN stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN stock_move_line sml ON sml.move_id = sm.id
INNER JOIN stock_lot sl ON sml.lot_id = sl.id
INNER JOIN stock_move_line po_sml ON po_sml.lot_id = sl.id
INNER JOIN stock_move po_sm ON po_sml.move_id = po_sm.id
INNER JOIN stock_location po_loc ON po_sm.location_id = po_loc.id
WHERE picking.id = po_sm.picking_id
  AND mo.name = 'WH/MO/800188'
  AND po_loc.usage = 'supplier'
  AND picking.state != 'cancel';

-- 6.2: Cancel purchase order moves
UPDATE stock_move po_sm
SET state = 'cancel'
FROM mrp_production mo
INNER JOIN stock_move sm ON sm.raw_material_production_id = mo.id
INNER JOIN stock_move_line sml ON sml.move_id = sm.id
INNER JOIN stock_lot sl ON sml.lot_id = sl.id
INNER JOIN stock_move_line po_sml ON po_sml.lot_id = sl.id
INNER JOIN stock_location po_loc ON po_sm.location_id = po_loc.id
WHERE po_sm.id = po_sml.move_id
  AND mo.name = 'WH/MO/800188'
  AND po_loc.usage = 'supplier'
  AND po_sm.state != 'cancel'
  AND po_sm.state != 'done';

-- 6.3: Reset qty_received in purchase order lines
UPDATE purchase_order_line pol
SET qty_received = 0,
    qty_received_manual = 0
FROM stock_move po_sm
INNER JOIN stock_location po_loc ON po_sm.location_id = po_loc.id
INNER JOIN stock_move_line po_sml ON po_sml.move_id = po_sm.id
INNER JOIN stock_lot sl ON po_sml.lot_id = sl.id
INNER JOIN stock_move_line sml ON sml.lot_id = sl.id
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_production mo ON sm.raw_material_production_id = mo.id
WHERE pol.id = po_sm.purchase_line_id
  AND pol.product_id = po_sm.product_id
  AND mo.name = 'WH/MO/800188'
  AND po_loc.usage = 'supplier';

-- 6.4: Reset purchase order state if all lines are reset
-- This allows the "Receive Products" button to work again
UPDATE purchase_order po
SET state = 'purchase'  -- Back to purchase state (can receive again)
WHERE po.id IN (
    SELECT DISTINCT pol.order_id
    FROM purchase_order_line pol
    INNER JOIN stock_move po_sm ON po_sm.purchase_line_id = pol.id
    INNER JOIN stock_location po_loc ON po_sm.location_id = po_loc.id
    INNER JOIN stock_move_line po_sml ON po_sml.move_id = po_sm.id
    INNER JOIN stock_lot sl ON po_sml.lot_id = sl.id
    INNER JOIN stock_move_line sml ON sml.lot_id = sl.id
    INNER JOIN stock_move sm ON sml.move_id = sm.id
    INNER JOIN mrp_production mo ON sm.raw_material_production_id = mo.id
    WHERE mo.name = 'WH/MO/800188'
      AND po_loc.usage = 'supplier'
)
AND po.state = 'done';

-- ============================================
-- STEP 7: DELETE MANUFACTURING ORDER
-- ============================================
-- Only delete if state allows (not 'done')

-- 7.1: Delete work orders
DELETE FROM mrp_workorder
WHERE production_id IN (
    SELECT id FROM mrp_production WHERE name = 'WH/MO/800188'
);

-- 7.2: Delete stock moves (if not done)
DELETE FROM stock_move
WHERE (raw_material_production_id IN (
    SELECT id FROM mrp_production WHERE name = 'WH/MO/800188'
) OR production_id IN (
    SELECT id FROM mrp_production WHERE name = 'WH/MO/800188'
))
AND state != 'done';

-- 7.3: Delete the manufacturing order itself
DELETE FROM mrp_production
WHERE name = 'WH/MO/800188'
AND state != 'done';  -- Safety check

-- ============================================
-- STEP 8: HANDLE ACCOUNTING ENTRIES
-- ============================================
-- WARNING: This is complex and may require manual review
-- Accounting entries should ideally be reversed, not deleted

-- 8.1: Cancel account moves related to stock moves
UPDATE account_move am
SET state = 'cancel'
FROM account_move_line aml
INNER JOIN stock_move sm ON aml.stock_move_id = sm.id
INNER JOIN mrp_production mo ON (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
WHERE am.id = aml.move_id
  AND mo.name = 'WH/MO/800188'
  AND am.state = 'posted';

-- 8.2: Delete draft account moves
DELETE FROM account_move_line aml
USING account_move am, stock_move sm, mrp_production mo
WHERE aml.move_id = am.id
  AND aml.stock_move_id = sm.id
  AND (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
  AND mo.name = 'WH/MO/800188'
  AND am.state = 'draft';

DELETE FROM account_move am
USING stock_move sm, mrp_production mo
WHERE EXISTS (
    SELECT 1 FROM account_move_line aml
    WHERE aml.move_id = am.id
      AND aml.stock_move_id = sm.id
)
AND (sm.raw_material_production_id = mo.id OR sm.production_id = mo.id)
AND mo.name = 'WH/MO/800188'
AND am.state = 'draft';

-- ============================================
-- VERIFICATION QUERIES
-- ============================================

-- Check if MO still exists
SELECT id, name, state FROM mrp_production WHERE name = 'WH/MO/800188';

-- Check remaining lots
SELECT sl.id, sl.name
FROM stock_lot sl
INNER JOIN stock_move_line sml ON sml.lot_id = sl.id
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_production mo ON sm.raw_material_production_id = mo.id
WHERE mo.name = 'WH/MO/800188';

-- Check purchase order states
SELECT po.id, po.name, po.state, pol.qty_received
FROM purchase_order po
LEFT JOIN purchase_order_line pol ON pol.order_id = po.id
WHERE po.id IN (
    SELECT DISTINCT pol2.order_id
    FROM purchase_order_line pol2
    INNER JOIN stock_move po_sm ON po_sm.purchase_line_id = pol2.id
    INNER JOIN stock_move_line po_sml ON po_sml.move_id = po_sm.id
    INNER JOIN stock_lot sl ON po_sml.lot_id = sl.id
    INNER JOIN stock_move_line sml ON sml.lot_id = sl.id
    INNER JOIN stock_move sm ON sml.move_id = sm.id
    INNER JOIN mrp_production mo ON sm.raw_material_production_id = mo.id
    WHERE mo.name = 'WH/MO/800188'
);
