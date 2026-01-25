-- ============================================
-- SIMPLE UNBUILD MANUFACTURING ORDER VIA SQL
-- ============================================
-- Step-by-step unbuild without DO blocks
-- Replace 'WH/MO/800188' with your MO name
-- ============================================

-- ============================================
-- STEP 1: Verify MO exists and get details
-- ============================================
-- Note: qty_produced is computed, so we calculate it from finished moves
SELECT 
    mo.id, mo.name, mo.state, mo.product_id, 
    COALESCE(SUM(fm.quantity_done), mo.product_qty) AS qty_produced,
    mo.product_uom_id, mo.location_src_id, mo.location_dest_id, mo.company_id
FROM mrp_production mo
LEFT JOIN stock_move fm ON fm.production_id = mo.id 
    AND fm.state = 'done' 
    AND fm.product_id = mo.product_id
WHERE mo.name = 'WH/MO/800188'
GROUP BY mo.id, mo.name, mo.state, mo.product_id, mo.product_qty, 
         mo.product_uom_id, mo.location_src_id, mo.location_dest_id, mo.company_id;

-- ============================================
-- STEP 2: Create Unbuild Order
-- ============================================
-- Get the next sequence number for unbuild
INSERT INTO mrp_unbuild (
    name,
    product_id,
    product_qty,
    product_uom_id,
    mo_id,
    company_id,
    location_id,
    location_dest_id,
    state,
    create_date,
    write_date,
    create_uid,
    write_uid
)
SELECT 
    'UNBUILD/' || mo.name,
    mo.product_id,
    COALESCE(SUM(fm.quantity_done), mo.product_qty),  -- Calculate from finished moves
    mo.product_uom_id,
    mo.id,
    mo.company_id,
    mo.location_dest_id,  -- Source location (where finished product is)
    mo.location_src_id,   -- Destination location (where to restore components)
    'done',
    NOW(),
    NOW(),
    1,
    1
FROM mrp_production mo
LEFT JOIN stock_move fm ON fm.production_id = mo.id 
    AND fm.state = 'done' 
    AND fm.product_id = mo.product_id
WHERE mo.name = 'WH/MO/800188'
  AND NOT EXISTS (SELECT 1 FROM mrp_unbuild WHERE mo_id = mo.id)
GROUP BY mo.id, mo.name, mo.product_id, mo.product_qty, mo.product_uom_id, 
         mo.company_id, mo.location_dest_id, mo.location_src_id;

-- Get the unbuild ID (use this in subsequent steps)
SELECT id AS unbuild_id FROM mrp_unbuild 
WHERE mo_id = (SELECT id FROM mrp_production WHERE name = 'WH/MO/800188')
ORDER BY id DESC LIMIT 1;

-- ============================================
-- STEP 3: Create Consume Moves (Finished Products)
-- ============================================
-- Replace <UNBUILD_ID> with the ID from step 2
INSERT INTO stock_move (
    name, date, product_id, product_uom_qty, product_uom,
    location_id, location_dest_id, state, procure_method,
    company_id, warehouse_id, unbuild_id, origin_returned_move_id,
    create_date, write_date, create_uid, write_uid
)
SELECT 
    'UNBUILD/' || mo.name || ' - Consume',
    NOW(),
    fm.product_id,
    fm.quantity_done,
    fm.product_uom,
    mo.location_dest_id,
    fm.location_id,
    'done',
    'make_to_stock',
    mo.company_id,
    loc_dest.warehouse_id,
    ub.id,
    fm.id,
    NOW(),
    NOW(),
    1,
    1
FROM mrp_production mo
INNER JOIN mrp_unbuild ub ON ub.mo_id = mo.id
INNER JOIN stock_move fm ON fm.production_id = mo.id
INNER JOIN stock_location loc_dest ON mo.location_dest_id = loc_dest.id
WHERE mo.name = 'WH/MO/800188'
  AND fm.state = 'done'
  AND fm.product_id = mo.product_id;

-- ============================================
-- STEP 4: Create Produce Moves (Raw Materials)
-- ============================================
INSERT INTO stock_move (
    name, date, product_id, product_uom_qty, product_uom,
    location_id, location_dest_id, state, procure_method,
    company_id, warehouse_id, unbuild_id, origin_returned_move_id,
    create_date, write_date, create_uid, write_uid
)
SELECT 
    'UNBUILD/' || mo.name || ' - Restore',
    NOW(),
    rm.product_id,
    rm.quantity_done,
    rm.product_uom,
    rm.location_dest_id,
    rm.location_id,
    'done',
    'make_to_stock',
    mo.company_id,
    loc_dest.warehouse_id,
    ub.id,
    rm.id,
    NOW(),
    NOW(),
    1,
    1
FROM mrp_production mo
INNER JOIN mrp_unbuild ub ON ub.mo_id = mo.id
INNER JOIN stock_move rm ON rm.raw_material_production_id = mo.id
INNER JOIN stock_location loc_dest ON rm.location_dest_id = loc_dest.id
WHERE mo.name = 'WH/MO/800188'
  AND rm.state = 'done';

-- ============================================
-- STEP 5: Create Move Lines for Consume Moves
-- ============================================
INSERT INTO stock_move_line (
    move_id, product_id, product_uom_id, location_id, location_dest_id,
    qty_done, reserved_uom_qty, lot_id, date, state, company_id,
    create_date, write_date, create_uid, write_uid
)
SELECT
    cm.id,
    fm.product_id,
    fm.product_uom,
    cm.location_id,
    cm.location_dest_id,
    COALESCE(fml.qty_done, fm.quantity_done),
    0.0 AS reserved_uom_qty,
    fml.lot_id,
    COALESCE(fml.date, fm.date, CURRENT_TIMESTAMP) AS date,
    'done',
    cm.company_id,
    NOW(),
    NOW(),
    1,
    1
FROM stock_move cm
INNER JOIN mrp_unbuild ub ON cm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
INNER JOIN stock_move fm ON cm.origin_returned_move_id = fm.id
LEFT JOIN stock_move_line fml ON fml.move_id = fm.id AND fml.qty_done > 0
WHERE mo.name = 'WH/MO/800188'
  AND cm.location_dest_id != cm.location_id
  AND NOT EXISTS (SELECT 1 FROM stock_move_line WHERE move_id = cm.id);

-- ============================================
-- STEP 6: Create Move Lines for Produce Moves (WITH LOTS)
-- ============================================
-- This is the critical step - restore the same lot IDs

INSERT INTO stock_move_line (
    move_id, product_id, product_uom_id, location_id, location_dest_id,
    qty_done, reserved_uom_qty, lot_id, date, state, company_id,
    create_date, write_date, create_uid, write_uid
)
SELECT
    pm.id,
    rml.product_id,
    rml.product_uom_id,
    pm.location_id,
    pm.location_dest_id,
    rml.qty_done,
    0.0 AS reserved_uom_qty,
    rml.lot_id,  -- CRITICAL: Same lot ID that was consumed
    COALESCE(rml.date, CURRENT_TIMESTAMP) AS date,
    'done',
    pm.company_id,
    NOW(),
    NOW(),
    1,
    1
FROM stock_move pm
INNER JOIN mrp_unbuild ub ON pm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
INNER JOIN stock_move rm ON pm.origin_returned_move_id = rm.id
INNER JOIN stock_move_line rml ON rml.move_id = rm.id AND rml.qty_done > 0
WHERE mo.name = 'WH/MO/800188'
  AND pm.location_id != pm.location_dest_id
  AND NOT EXISTS (
      SELECT 1 FROM stock_move_line 
      WHERE move_id = pm.id AND lot_id = rml.lot_id
  );

-- ============================================
-- STEP 7: Update Stock Quants - Remove Finished Products
-- ============================================
UPDATE stock_quant sq
SET quantity = quantity - sml.qty_done
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE sq.product_id = sml.product_id
  AND sq.location_id = sml.location_id
  AND sq.lot_id = COALESCE(sml.lot_id, sq.lot_id)
  AND sq.company_id = sm.company_id
  AND mo.name = 'WH/MO/800188'
  AND sm.location_dest_id != sm.location_id
  AND sml.qty_done > 0
  AND sq.quantity >= sml.qty_done;

-- ============================================
-- STEP 8: Update Stock Quants - Add Finished Products to Production
-- ============================================
-- Insert new quants
INSERT INTO stock_quant (product_id, location_id, lot_id, quantity, reserved_quantity, in_date, company_id, create_date, write_date, create_uid, write_uid)
SELECT DISTINCT
    sml.product_id,
    sml.location_dest_id,
    sml.lot_id,
    sml.qty_done,
    0.0 AS reserved_quantity,
    NOW() AS in_date,
    sm.company_id,
    NOW(),
    NOW(),
    1,
    1
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE mo.name = 'WH/MO/800188'
  AND sm.location_dest_id != sm.location_id
  AND sml.qty_done > 0
  AND NOT EXISTS (
      SELECT 1 FROM stock_quant 
      WHERE product_id = sml.product_id 
        AND location_id = sml.location_dest_id 
        AND lot_id = COALESCE(sml.lot_id, lot_id)
        AND company_id = sm.company_id
  );

-- Update existing quants
UPDATE stock_quant sq
SET quantity = quantity + sml.qty_done
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE sq.product_id = sml.product_id
  AND sq.location_id = sml.location_dest_id
  AND sq.lot_id = COALESCE(sml.lot_id, sq.lot_id)
  AND sq.company_id = sm.company_id
  AND mo.name = 'WH/MO/800188'
  AND sm.location_dest_id != sm.location_id
  AND sml.qty_done > 0;

-- ============================================
-- STEP 9: Update Stock Quants - Remove Raw Materials from Production
-- ============================================
UPDATE stock_quant sq
SET quantity = GREATEST(0, quantity - sml.qty_done)
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE sq.product_id = sml.product_id
  AND sq.location_id = sml.location_id
  AND sq.lot_id = COALESCE(sml.lot_id, sq.lot_id)
  AND sq.company_id = sm.company_id
  AND mo.name = 'WH/MO/800188'
  AND sm.location_id != sm.location_dest_id
  AND sml.qty_done > 0
  AND sq.quantity >= sml.qty_done;

-- ============================================
-- STEP 10: Update Stock Quants - RESTORE LOTS TO SOURCE LOCATIONS
-- ============================================
-- This is the most important step - restore lots with same lot IDs

-- Insert new quants with lots
INSERT INTO stock_quant (product_id, location_id, lot_id, quantity, reserved_quantity, in_date, company_id, create_date, write_date, create_uid, write_uid)
SELECT DISTINCT
    sml.product_id,
    sml.location_dest_id,
    sml.lot_id,
    sml.qty_done,
    0.0 AS reserved_quantity,
    NOW() AS in_date,
    sm.company_id,
    NOW(),
    NOW(),
    1,
    1
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE mo.name = 'WH/MO/800188'
  AND sm.location_id != sm.location_dest_id
  AND sml.qty_done > 0
  AND sml.lot_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM stock_quant 
      WHERE product_id = sml.product_id 
        AND location_id = sml.location_dest_id 
        AND lot_id = sml.lot_id
        AND company_id = sm.company_id
  );

-- Update existing quants with lots
UPDATE stock_quant sq
SET quantity = quantity + sml.qty_done
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE sq.product_id = sml.product_id
  AND sq.location_id = sml.location_dest_id
  AND sq.lot_id = sml.lot_id
  AND sq.company_id = sm.company_id
  AND mo.name = 'WH/MO/800188'
  AND sm.location_id != sm.location_dest_id
  AND sml.qty_done > 0
  AND sml.lot_id IS NOT NULL;

-- For non-tracked products
INSERT INTO stock_quant (product_id, location_id, lot_id, quantity, reserved_quantity, in_date, company_id, create_date, write_date, create_uid, write_uid)
SELECT DISTINCT
    sml.product_id,
    sml.location_dest_id,
    NULL,
    sml.qty_done,
    0.0 AS reserved_quantity,
    NOW() AS in_date,
    sm.company_id,
    NOW(),
    NOW(),
    1,
    1
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE mo.name = 'WH/MO/800188'
  AND sm.location_id != sm.location_dest_id
  AND sml.qty_done > 0
  AND sml.lot_id IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM stock_quant 
      WHERE product_id = sml.product_id 
        AND location_id = sml.location_dest_id 
        AND lot_id IS NULL
        AND company_id = sm.company_id
  );

UPDATE stock_quant sq
SET quantity = quantity + sml.qty_done
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE sq.product_id = sml.product_id
  AND sq.location_id = sml.location_dest_id
  AND sq.lot_id IS NULL
  AND sq.company_id = sm.company_id
  AND mo.name = 'WH/MO/800188'
  AND sm.location_id != sm.location_dest_id
  AND sml.qty_done > 0
  AND sml.lot_id IS NULL;

-- ============================================
-- VERIFICATION: Check restored lots
-- ============================================
SELECT 
    sl.id AS lot_id,
    sl.name AS lot_name,
    pt.name AS product_name,
    loc.complete_name AS location,
    sq.quantity AS restored_quantity
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
