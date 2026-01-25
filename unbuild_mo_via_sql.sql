-- ============================================
-- UNBUILD MANUFACTURING ORDER VIA SQL
-- ============================================
-- This script replicates the unbuild functionality using SQL queries.
-- It restores consumed lots back to inventory without affecting accounting.
--
-- WARNING: Backup your database before running!
-- 
-- Usage: Replace 'WH/MO/800188' with your manufacturing order name
-- ============================================

-- ============================================
-- STEP 1: PREPARATION - Get MO Information
-- ============================================
-- First, verify the MO exists and get its details

DO $$
DECLARE
    mo_id_var INTEGER;
    mo_name_var VARCHAR;
    mo_state_var VARCHAR;
    mo_product_id_var INTEGER;
    mo_qty_produced_var NUMERIC;
    mo_uom_id_var INTEGER;
    mo_location_id_var INTEGER;
    mo_location_dest_id_var INTEGER;
    mo_company_id_var INTEGER;
    mo_warehouse_id_var INTEGER;
BEGIN
    -- Get MO details
    -- Note: qty_produced is computed, so we calculate it from finished moves
    SELECT mo.id, mo.name, mo.state, mo.product_id, 
           COALESCE(SUM(fm.quantity_done), mo.product_qty) AS qty_produced,
           mo.product_uom_id, mo.location_src_id, mo.location_dest_id, mo.company_id
    INTO mo_id_var, mo_name_var, mo_state_var, mo_product_id_var, 
         mo_qty_produced_var, mo_uom_id_var, mo_location_id_var, 
         mo_location_dest_id_var, mo_company_id_var
    FROM mrp_production mo
    LEFT JOIN stock_move fm ON fm.production_id = mo.id 
        AND fm.state = 'done' 
        AND fm.product_id = mo.product_id
    WHERE mo.name = 'WH/MO/800188'  -- Replace with your MO name
    GROUP BY mo.id, mo.name, mo.state, mo.product_id, mo.product_qty, 
             mo.product_uom_id, mo.location_src_id, mo.location_dest_id, mo.company_id;
    
    IF mo_id_var IS NULL THEN
        RAISE EXCEPTION 'Manufacturing order not found!';
    END IF;
    
    IF mo_state_var != 'done' THEN
        RAISE EXCEPTION 'Manufacturing order must be in done state to unbuild!';
    END IF;
    
    -- Get warehouse from location
    SELECT warehouse_id INTO mo_warehouse_id_var
    FROM stock_location
    WHERE id = mo_location_dest_id_var;
    
    RAISE NOTICE 'MO Found: %, State: %, Product: %, Qty Produced: %', 
        mo_name_var, mo_state_var, mo_product_id_var, mo_qty_produced_var;
END $$;

-- ============================================
-- STEP 2: CREATE UNBUILD ORDER RECORD
-- ============================================
-- Create an unbuild order record (optional, for tracking)

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
    'done',  -- Mark as done immediately since we're doing it via SQL
    NOW(),
    NOW(),
    1,  -- System user
    1   -- System user
FROM mrp_production mo
LEFT JOIN stock_move fm ON fm.production_id = mo.id 
    AND fm.state = 'done' 
    AND fm.product_id = mo.product_id
WHERE mo.name = 'WH/MO/800188'
  AND NOT EXISTS (
      SELECT 1 FROM mrp_unbuild WHERE mo_id = mo.id
  )
GROUP BY mo.id, mo.name, mo.product_id, mo.product_qty, mo.product_uom_id, 
         mo.company_id, mo.location_dest_id, mo.location_src_id
RETURNING id AS unbuild_id;

-- ============================================
-- STEP 3: CREATE CONSUME MOVES (Finished Products)
-- ============================================
-- These moves consume the finished products (move them out of stock)

-- Get the unbuild ID we just created
DO $$
DECLARE
    unbuild_id_var INTEGER;
    mo_id_var INTEGER;
BEGIN
    SELECT id INTO unbuild_id_var
    FROM mrp_unbuild
    WHERE mo_id = (SELECT id FROM mrp_production WHERE name = 'WH/MO/800188')
    ORDER BY id DESC
    LIMIT 1;
    
    SELECT id INTO mo_id_var
    FROM mrp_production
    WHERE name = 'WH/MO/800188';
    
    -- Create consume moves for finished products
    INSERT INTO stock_move (
        name,
        date,
        product_id,
        product_uom_qty,
        product_uom,
        location_id,
        location_dest_id,
        state,
        procure_method,
        company_id,
        warehouse_id,
        unbuild_id,
        origin_returned_move_id,
        create_date,
        write_date,
        create_uid,
        write_uid
    )
    SELECT 
        'UNBUILD/' || mo.name || ' - Consume',
        NOW(),
        fm.product_id,
        fm.quantity_done,  -- Full quantity that was produced
        fm.product_uom,
        mo.location_dest_id,  -- From stock (where finished product is)
        fm.location_id,  -- Back to production location
        'done',  -- Mark as done
        'make_to_stock',
        mo.company_id,
        loc_dest.warehouse_id,
        unbuild_id_var,
        fm.id,  -- Reference to original finished move
        NOW(),
        NOW(),
        1,
        1
    FROM mrp_production mo
    INNER JOIN stock_move fm ON fm.production_id = mo.id
    INNER JOIN stock_location loc_dest ON mo.location_dest_id = loc_dest.id
    WHERE mo.id = mo_id_var
      AND fm.state = 'done'
      AND fm.product_id = mo.product_id;  -- Only finished product moves
    
    RAISE NOTICE 'Consume moves created';
END $$;

-- ============================================
-- STEP 4: CREATE PRODUCE MOVES (Raw Materials)
-- ============================================
-- These moves restore raw materials back to inventory with original lots

DO $$
DECLARE
    unbuild_id_var INTEGER;
    mo_id_var INTEGER;
    mo_qty_produced_var NUMERIC;
    mo_uom_id_var INTEGER;
    factor_var NUMERIC;
BEGIN
    SELECT id INTO unbuild_id_var
    FROM mrp_unbuild
    WHERE mo_id = (SELECT id FROM mrp_production WHERE name = 'WH/MO/800188')
    ORDER BY id DESC
    LIMIT 1;
    
    -- Calculate qty_produced from finished moves
    SELECT mo.id, 
           COALESCE(SUM(fm.quantity_done), mo.product_qty) AS qty_produced,
           mo.product_uom_id 
    INTO mo_id_var, mo_qty_produced_var, mo_uom_id_var
    FROM mrp_production mo
    LEFT JOIN stock_move fm ON fm.production_id = mo.id 
        AND fm.state = 'done' 
        AND fm.product_id = mo.product_id
    WHERE mo.name = 'WH/MO/800188'
    GROUP BY mo.id, mo.product_qty, mo.product_uom_id;
    
    -- Factor is 1.0 if we're unbuilding the full quantity
    factor_var := 1.0;
    
    -- Create produce moves for raw materials
    INSERT INTO stock_move (
        name,
        date,
        product_id,
        product_uom_qty,
        product_uom,
        location_id,
        location_dest_id,
        state,
        procure_method,
        company_id,
        warehouse_id,
        unbuild_id,
        origin_returned_move_id,
        create_date,
        write_date,
        create_uid,
        write_uid
    )
    SELECT 
        'UNBUILD/' || mo.name || ' - Restore',
        NOW(),
        rm.product_id,
        rm.quantity_done * factor_var,  -- Restore the consumed quantity
        rm.product_uom,
        rm.location_dest_id,  -- From production location (where it was consumed)
        rm.location_id,  -- Back to original source location
        'done',  -- Mark as done
        'make_to_stock',
        mo.company_id,
        loc_dest.warehouse_id,
        unbuild_id_var,
        rm.id,  -- Reference to original raw material move
        NOW(),
        NOW(),
        1,
        1
    FROM mrp_production mo
    INNER JOIN stock_move rm ON rm.raw_material_production_id = mo.id
    INNER JOIN stock_location loc_dest ON rm.location_dest_id = loc_dest.id
    WHERE mo.id = mo_id_var
      AND rm.state = 'done';
    
    RAISE NOTICE 'Produce moves created';
END $$;

-- ============================================
-- STEP 5: CREATE MOVE LINES WITH LOT NUMBERS
-- ============================================
-- This is the critical part - restore the lots with the same lot IDs

DO $$
DECLARE
    unbuild_id_var INTEGER;
    mo_id_var INTEGER;
    produce_move_id_var INTEGER;
    consume_move_id_var INTEGER;
BEGIN
    SELECT id INTO unbuild_id_var
    FROM mrp_unbuild
    WHERE mo_id = (SELECT id FROM mrp_production WHERE name = 'WH/MO/800188')
    ORDER BY id DESC
    LIMIT 1;
    
    SELECT id INTO mo_id_var
    FROM mrp_production
    WHERE name = 'WH/MO/800188';
    
    -- Create move lines for CONSUME moves (finished products)
    INSERT INTO stock_move_line (
        move_id,
        product_id,
        product_uom_id,
        location_id,
        location_dest_id,
        qty_done,
        reserved_uom_qty,
        lot_id,
        date,
        state,
        company_id,
        create_date,
        write_date,
        create_uid,
        write_uid
    )
    SELECT 
        cm.id AS move_id,
        fm.product_id,
        fm.product_uom,
        cm.location_id,
        cm.location_dest_id,
        COALESCE(fml.qty_done, fm.quantity_done),  -- Quantity that was produced
        0.0 AS reserved_uom_qty,  -- No reservation needed for done moves
        fml.lot_id,  -- Lot of finished product (if tracked)
        COALESCE(fml.date, fm.date, CURRENT_TIMESTAMP) AS date,  -- Required date field
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
    WHERE cm.unbuild_id = unbuild_id_var
      AND cm.location_dest_id != cm.location_id  -- Consume moves
      AND NOT EXISTS (
          SELECT 1 FROM stock_move_line WHERE move_id = cm.id
      );
    
    -- Create move lines for PRODUCE moves (raw materials with lots)
    INSERT INTO stock_move_line (
        move_id,
        product_id,
        product_uom_id,
        location_id,
        location_dest_id,
        qty_done,
        reserved_uom_qty,
        lot_id,
        date,
        state,
        company_id,
        create_date,
        write_date,
        create_uid,
        write_uid
    )
    SELECT 
        pm.id AS move_id,
        rml.product_id,
        rml.product_uom_id,
        pm.location_id,
        pm.location_dest_id,
        rml.qty_done,  -- Restore the exact quantity consumed
        0.0 AS reserved_uom_qty,  -- No reservation needed for done moves
        rml.lot_id,  -- CRITICAL: Restore the same lot ID that was consumed
        COALESCE(rml.date, CURRENT_TIMESTAMP) AS date,  -- Required date field
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
    WHERE pm.unbuild_id = unbuild_id_var
      AND pm.location_id != pm.location_dest_id  -- Produce moves
      AND rml.lot_id IS NOT NULL  -- Only tracked products
      AND NOT EXISTS (
          SELECT 1 FROM stock_move_line WHERE move_id = pm.id AND lot_id = rml.lot_id
      );
    
    -- For non-tracked products, create move lines without lot_id
    INSERT INTO stock_move_line (
        move_id,
        product_id,
        product_uom_id,
        location_id,
        location_dest_id,
        qty_done,
        reserved_uom_qty,
        date,
        state,
        company_id,
        create_date,
        write_date,
        create_uid,
        write_uid
    )
    SELECT 
        pm.id AS move_id,
        rml.product_id,
        rml.product_uom_id,
        pm.location_id,
        pm.location_dest_id,
        rml.qty_done,
        0.0 AS reserved_uom_qty,  -- No reservation needed for done moves
        COALESCE(rml.date, CURRENT_TIMESTAMP) AS date,  -- Required date field
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
    WHERE pm.unbuild_id = unbuild_id_var
      AND pm.location_id != pm.location_dest_id
      AND rml.lot_id IS NULL  -- Non-tracked products
      AND NOT EXISTS (
          SELECT 1 FROM stock_move_line WHERE move_id = pm.id
      );
    
    RAISE NOTICE 'Move lines created with lot numbers';
END $$;

-- ============================================
-- STEP 6: UPDATE STOCK QUANTS
-- ============================================
-- Update inventory quantities to reflect the unbuild

-- 6.1: Remove finished products from stock (consume moves)
UPDATE stock_quant sq
SET quantity = quantity - sml.qty_done
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE sq.product_id = sml.product_id
  AND sq.location_id = sml.location_id  -- Source location (where finished product is)
  AND sq.lot_id = COALESCE(sml.lot_id, sq.lot_id)
  AND mo.name = 'WH/MO/800188'
  AND sm.location_dest_id != sm.location_id  -- Consume moves
  AND sml.qty_done > 0
  AND sq.quantity >= sml.qty_done;

-- 6.2: Add finished products back to production location (consume moves destination)
INSERT INTO stock_quant (product_id, location_id, lot_id, quantity, reserved_quantity, in_date, company_id, create_date, write_date, create_uid, write_uid)
SELECT 
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
  AND sm.location_dest_id != sm.location_id  -- Consume moves
  AND sml.qty_done > 0
  AND NOT EXISTS (
      SELECT 1 FROM stock_quant 
      WHERE product_id = sml.product_id 
        AND location_id = sml.location_dest_id 
        AND lot_id = COALESCE(sml.lot_id, lot_id)
        AND company_id = sm.company_id
  )
ON CONFLICT DO NOTHING;

-- Update existing quants in production location
UPDATE stock_quant sq
SET quantity = quantity + sml.qty_done
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE sq.product_id = sml.product_id
  AND sq.location_id = sml.location_dest_id  -- Production location
  AND sq.lot_id = COALESCE(sml.lot_id, sq.lot_id)
  AND sq.company_id = sm.company_id
  AND mo.name = 'WH/MO/800188'
  AND sm.location_dest_id != sm.location_id  -- Consume moves
  AND sml.qty_done > 0;

-- 6.3: Remove raw materials from production location (produce moves source)
UPDATE stock_quant sq
SET quantity = GREATEST(0, quantity - sml.qty_done)
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE sq.product_id = sml.product_id
  AND sq.location_id = sml.location_id  -- Production location (source)
  AND sq.lot_id = COALESCE(sml.lot_id, sq.lot_id)
  AND sq.company_id = sm.company_id
  AND mo.name = 'WH/MO/800188'
  AND sm.location_id != sm.location_dest_id  -- Produce moves
  AND sml.qty_done > 0
  AND sq.quantity >= sml.qty_done;

-- 6.4: Add raw materials back to source locations WITH LOTS (produce moves destination)
-- This is the critical part - restore lots to their original locations
INSERT INTO stock_quant (product_id, location_id, lot_id, quantity, reserved_quantity, in_date, company_id, create_date, write_date, create_uid, write_uid)
SELECT 
    sml.product_id,
    sml.location_dest_id,  -- Original source location
    sml.lot_id,  -- CRITICAL: Same lot ID that was consumed
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
  AND sm.location_id != sm.location_dest_id  -- Produce moves
  AND sml.qty_done > 0
  AND sml.lot_id IS NOT NULL  -- Only tracked products
  AND NOT EXISTS (
      SELECT 1 FROM stock_quant 
      WHERE product_id = sml.product_id 
        AND location_id = sml.location_dest_id 
        AND lot_id = sml.lot_id
        AND company_id = sm.company_id
  )
ON CONFLICT DO NOTHING;

-- Update existing quants in source locations
UPDATE stock_quant sq
SET quantity = quantity + sml.qty_done
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE sq.product_id = sml.product_id
  AND sq.location_id = sml.location_dest_id  -- Original source location
  AND sq.lot_id = sml.lot_id  -- Same lot ID
  AND sq.company_id = sm.company_id
  AND mo.name = 'WH/MO/800188'
  AND sm.location_id != sm.location_dest_id  -- Produce moves
  AND sml.qty_done > 0
  AND sml.lot_id IS NOT NULL;

-- For non-tracked products
INSERT INTO stock_quant (product_id, location_id, lot_id, quantity, reserved_quantity, in_date, company_id, create_date, write_date, create_uid, write_uid)
SELECT 
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
  )
ON CONFLICT DO NOTHING;

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
-- STEP 7: VERIFICATION
-- ============================================
-- Check that lots have been restored

SELECT 
    'Lots Restored' AS status,
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
  AND sm.location_id != sm.location_dest_id  -- Produce moves
  AND sml.qty_done > 0
ORDER BY sl.name, pt.name;

-- ============================================
-- SUMMARY
-- ============================================
SELECT 
    'Unbuild Complete' AS status,
    mo.name AS manufacturing_order,
    ub.name AS unbuild_order,
    COUNT(DISTINCT sm.id) AS total_moves_created,
    COUNT(DISTINCT sml.id) AS total_move_lines_created,
    COUNT(DISTINCT sml.lot_id) AS lots_restored
FROM mrp_production mo
INNER JOIN mrp_unbuild ub ON ub.mo_id = mo.id
LEFT JOIN stock_move sm ON sm.unbuild_id = ub.id
LEFT JOIN stock_move_line sml ON sml.move_id = sm.id
WHERE mo.name = 'WH/MO/800188'
GROUP BY mo.name, ub.name;
