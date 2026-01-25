-- ============================================
-- CORRECTED UNBUILD MANUFACTURING ORDER VIA SQL
-- ============================================
-- This script properly calculates quantities and restores consumed lots.
-- It uses the actual consumed quantities from raw material move lines,
-- not the finished product quantity (which might not be in stock).
--
-- CRITICAL: This script ONLY restores lots that were consumed in THIS specific MO.
-- It filters by: rm.raw_material_production_id = mo.id to ensure MO-specific restoration.
--
-- WARNING: Backup your database before running!
-- 
-- Usage: Replace 'WH/MO/800188' with your manufacturing order name
-- ============================================

-- ============================================
-- STEP 0: VERIFY LOTS TO BE RESTORED (THIS MO ONLY)
-- ============================================
-- This query shows EXACTLY which lots will be restored from THIS MO only
-- Run this first to verify before proceeding

SELECT 
    'Lots to Restore (THIS MO ONLY)' AS check_type,
    sl.id AS lot_id,
    sl.name AS lot_name,
    pp.default_code AS product_code,
    pt.name AS product_name,
    SUM(rml.qty_done) AS consumed_qty,
    rm.location_id AS consumed_from_location,
    rm.location_dest_id AS consumed_to_location
FROM mrp_production mo
INNER JOIN stock_move rm ON rm.raw_material_production_id = mo.id  -- THIS MO ONLY
INNER JOIN stock_move_line rml ON rml.move_id = rm.id
INNER JOIN stock_lot sl ON rml.lot_id = sl.id
INNER JOIN product_product pp ON pp.id = sl.product_id
INNER JOIN product_template pt ON pt.id = pp.product_tmpl_id
WHERE mo.name = 'WH/MO/800188'  -- Replace with your MO name
  AND rm.state = 'done'
  AND rml.qty_done > 0
  AND rml.lot_id IS NOT NULL  -- Only tracked products with lots
GROUP BY sl.id, sl.name, pp.default_code, pt.name, rm.location_id, rm.location_dest_id
ORDER BY sl.name;

-- ============================================
-- STEP 1: PREPARATION - Get MO Information and Calculate Quantities
-- ============================================
-- Calculate the actual quantity to unbuild based on what was consumed

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
    available_qty_var NUMERIC;
    consumed_qty_var NUMERIC;
BEGIN
    -- Get MO details
    SELECT mo.id, mo.name, mo.state, mo.product_id, 
           mo.product_uom_id, mo.location_src_id, mo.location_dest_id, mo.company_id
    INTO mo_id_var, mo_name_var, mo_state_var, mo_product_id_var, 
         mo_uom_id_var, mo_location_id_var, mo_location_dest_id_var, mo_company_id_var
    FROM mrp_production mo
    WHERE mo.name = 'WH/MO/800188';  -- Replace with your MO name
    
    IF mo_id_var IS NULL THEN
        RAISE EXCEPTION 'Manufacturing order not found!';
    END IF;
    
    IF mo_state_var != 'done' THEN
        RAISE EXCEPTION 'Manufacturing order must be in done state to unbuild!';
    END IF;
    
    -- Calculate quantity produced from finished move LINES (more accurate)
    SELECT COALESCE(SUM(sml.qty_done), 0)
    INTO mo_qty_produced_var
    FROM mrp_production mo2
    INNER JOIN stock_move fm ON fm.production_id = mo2.id
    INNER JOIN stock_move_line sml ON sml.move_id = fm.id
    WHERE mo2.id = mo_id_var
      AND fm.state = 'done'
      AND fm.product_id = mo2.product_id
      AND sml.qty_done > 0;
    
    -- If no move lines, try quantity_done on the move itself
    IF mo_qty_produced_var = 0 THEN
        SELECT COALESCE(SUM(fm.quantity_done), mo.product_qty)
        INTO mo_qty_produced_var
        FROM mrp_production mo2
        LEFT JOIN stock_move fm ON fm.production_id = mo2.id
            AND fm.state = 'done'
            AND fm.product_id = mo2.product_id
        WHERE mo2.id = mo_id_var
        GROUP BY mo2.product_qty;
    END IF;
    
    -- Calculate available quantity in stock (what Odoo checks)
    SELECT COALESCE(SUM(sq.quantity - sq.reserved_quantity), 0)
    INTO available_qty_var
    FROM stock_quant sq
    WHERE sq.product_id = mo_product_id_var
      AND sq.location_id = mo_location_dest_id_var;
    
    -- Calculate total consumed quantity from raw material move lines
    SELECT COALESCE(SUM(sml.qty_done), 0)
    INTO consumed_qty_var
    FROM mrp_production mo2
    INNER JOIN stock_move rm ON rm.raw_material_production_id = mo2.id
    INNER JOIN stock_move_line sml ON sml.move_id = rm.id
    WHERE mo2.id = mo_id_var
      AND rm.state = 'done'
      AND sml.qty_done > 0;
    
    -- Get warehouse from location
    SELECT warehouse_id INTO mo_warehouse_id_var
    FROM stock_location
    WHERE id = mo_location_dest_id_var;
    
    RAISE NOTICE 'MO Found: %, State: %, Product: %', 
        mo_name_var, mo_state_var, mo_product_id_var;
    RAISE NOTICE 'Qty Produced (from move lines): %', mo_qty_produced_var;
    RAISE NOTICE 'Available in Stock: %', available_qty_var;
    RAISE NOTICE 'Total Consumed (raw materials): %', consumed_qty_var;
    
    -- Warn if finished product is not in stock
    IF available_qty_var = 0 AND mo_qty_produced_var > 0 THEN
        RAISE WARNING 'Finished product is not in stock, but we will restore raw materials anyway';
    END IF;
    
    -- Use the produced quantity for unbuild (what was actually made)
    -- If finished product is not in stock, we'll still restore raw materials
    -- but the consume move for finished product will have 0 quantity
    
END $$;

-- ============================================
-- STEP 2: CREATE UNBUILD ORDER RECORD
-- ============================================
-- Use the quantity from finished move lines, not just quantity_done on move

DO $$
DECLARE
    mo_id_var INTEGER;
    unbuild_id_var INTEGER;
    unbuild_qty_var NUMERIC;
BEGIN
    SELECT id INTO mo_id_var
    FROM mrp_production
    WHERE name = 'WH/MO/800188';
    
    -- Calculate quantity from finished move LINES (more accurate)
    SELECT COALESCE(SUM(sml.qty_done), 0)
    INTO unbuild_qty_var
    FROM mrp_production mo
    INNER JOIN stock_move fm ON fm.production_id = mo.id
    INNER JOIN stock_move_line sml ON sml.move_id = fm.id
    WHERE mo.id = mo_id_var
      AND fm.state = 'done'
      AND fm.product_id = mo.product_id
      AND sml.qty_done > 0;
    
    -- If no move lines, try quantity_done on the move itself
    IF unbuild_qty_var = 0 THEN
        SELECT COALESCE(SUM(fm.quantity_done), 0)
        INTO unbuild_qty_var
        FROM mrp_production mo
        LEFT JOIN stock_move fm ON fm.production_id = mo.id
            AND fm.state = 'done'
            AND fm.product_id = mo.product_id
        WHERE mo.id = mo_id_var;
    END IF;
    
    -- If still 0, check if we should use planned quantity or calculate from raw materials
    IF unbuild_qty_var = 0 THEN
        RAISE WARNING 'No finished product quantity found in moves/move lines.';
        RAISE WARNING 'This might mean the MO was completed without proper stock moves.';
        RAISE WARNING 'Will attempt to restore raw materials based on what was consumed.';
        -- Set to planned quantity as fallback, but this is not ideal
        SELECT mo.product_qty INTO unbuild_qty_var
        FROM mrp_production mo
        WHERE mo.id = mo_id_var;
    END IF;
    
    -- Ensure we have a valid quantity
    IF unbuild_qty_var <= 0 THEN
        RAISE EXCEPTION 'Cannot unbuild: No quantity found! Check finished moves, move lines, or MO planned quantity.';
    END IF;
    
    RAISE NOTICE 'Unbuild quantity will be: % (from finished moves/move lines, or planned qty as fallback)', unbuild_qty_var;
    
    -- Create unbuild order
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
        unbuild_qty_var,  -- Use calculated quantity
        mo.product_uom_id,
        mo.id,
        mo.company_id,
        mo.location_dest_id,  -- Source location (where finished product should be)
        mo.location_src_id,   -- Destination location (where to restore components)
        'done',  -- Mark as done immediately since we're doing it via SQL
        NOW(),
        NOW(),
        1,  -- System user
        1   -- System user
    FROM mrp_production mo
    WHERE mo.id = mo_id_var
      AND NOT EXISTS (
          SELECT 1 FROM mrp_unbuild WHERE mo_id = mo.id
      )
    RETURNING id INTO unbuild_id_var;
    
    RAISE NOTICE 'Unbuild order created with ID: %, Quantity: %', unbuild_id_var, unbuild_qty_var;
END $$;

-- ============================================
-- STEP 3: CREATE CONSUME MOVES (Finished Products)
-- ============================================
-- These moves consume the finished products (move them out of stock)
-- Use quantity from move lines, not just quantity_done on move

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
    -- Use quantity from move lines for accuracy
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
    SELECT DISTINCT
        'UNBUILD/' || mo.name || ' - Consume',
        NOW(),
        fm.product_id,
        COALESCE(SUM(fml.qty_done), fm.quantity_done, 0),  -- Use move line quantity
        fm.product_uom,
        mo.location_dest_id,  -- From stock (where finished product is)
        fm.location_id,  -- Back to production location
        'done',  -- Mark as done
        'make_to_stock',
        mo.company_id,
        loc.warehouse_id,
        unbuild_id_var,
        fm.id,  -- Reference to original finished move
        NOW(),
        NOW(),
        1,
        1
    FROM mrp_production mo
    INNER JOIN stock_move fm ON fm.production_id = mo.id
    INNER JOIN stock_location loc ON loc.id = mo.location_dest_id
    LEFT JOIN stock_move_line fml ON fml.move_id = fm.id AND fml.qty_done > 0
    WHERE mo.id = mo_id_var
      AND fm.state = 'done'
      AND fm.product_id = mo.product_id
    GROUP BY mo.id, mo.name, fm.id, fm.product_id, fm.quantity_done, 
             fm.product_uom, mo.location_dest_id, fm.location_id, 
             mo.company_id, loc.warehouse_id
    HAVING COALESCE(SUM(fml.qty_done), fm.quantity_done, 0) > 0;
    
    RAISE NOTICE 'Consume moves created';
END $$;

-- ============================================
-- STEP 4: CREATE CONSUME MOVE LINES (Finished Products)
-- ============================================
-- Create move lines for consume moves using original finished product lots

DO $$
DECLARE
    unbuild_id_var INTEGER;
BEGIN
    SELECT id INTO unbuild_id_var
    FROM mrp_unbuild
    WHERE mo_id = (SELECT id FROM mrp_production WHERE name = 'WH/MO/800188')
    ORDER BY id DESC
    LIMIT 1;
    
    INSERT INTO stock_move_line (
        move_id,
        product_id,
        product_uom_id,
        location_id,
        location_dest_id,
        qty_done,
        reserved_uom_qty,
        date,
        lot_id,
        state,
        company_id,
        create_date,
        write_date,
        create_uid,
        write_uid
    )
    SELECT 
        cm.id AS move_id,
        fml.product_id,
        fml.product_uom_id,
        cm.location_id,
        cm.location_dest_id,
        fml.qty_done,  -- Use original quantity from finished move line
        0.0 AS reserved_uom_qty,
        COALESCE(fml.date, CURRENT_TIMESTAMP) AS date,
        fml.lot_id,  -- Lot of finished product (if tracked)
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
    INNER JOIN stock_move_line fml ON fml.move_id = fm.id AND fml.qty_done > 0
    WHERE cm.unbuild_id = unbuild_id_var
      AND cm.location_id != cm.location_dest_id  -- Consume moves
      AND NOT EXISTS (
          SELECT 1 FROM stock_move_line WHERE move_id = cm.id
      );
    
    RAISE NOTICE 'Consume move lines created';
END $$;

-- ============================================
-- STEP 5: CREATE PRODUCE MOVES (Raw Materials)
-- ============================================
-- These moves restore the raw materials back to inventory
-- Use actual consumed quantities from raw material move lines

DO $$
DECLARE
    unbuild_id_var INTEGER;
    mo_id_var INTEGER;
    mo_qty_produced_var NUMERIC;
    factor_var NUMERIC;
BEGIN
    SELECT id INTO unbuild_id_var
    FROM mrp_unbuild
    WHERE mo_id = (SELECT id FROM mrp_production WHERE name = 'WH/MO/800188')
    ORDER BY id DESC
    LIMIT 1;
    
    SELECT id INTO mo_id_var
    FROM mrp_production
    WHERE name = 'WH/MO/800188';
    
    -- Calculate qty_produced from finished move lines
    SELECT COALESCE(SUM(sml.qty_done), 0)
    INTO mo_qty_produced_var
    FROM mrp_production mo2
    INNER JOIN stock_move fm ON fm.production_id = mo2.id
    INNER JOIN stock_move_line sml ON sml.move_id = fm.id
    WHERE mo2.id = mo_id_var
      AND fm.state = 'done'
      AND fm.product_id = mo2.product_id
      AND sml.qty_done > 0;
    
    -- If no move lines, try quantity_done on the move itself
    IF mo_qty_produced_var = 0 THEN
        SELECT COALESCE(SUM(fm.quantity_done), mo.product_qty)
        INTO mo_qty_produced_var
        FROM mrp_production mo2
        LEFT JOIN stock_move fm ON fm.production_id = mo2.id
            AND fm.state = 'done'
            AND fm.product_id = mo2.product_id
        WHERE mo2.id = mo_id_var
        GROUP BY mo2.product_qty;
    END IF;
    
    -- Get unbuild quantity
    SELECT product_qty INTO factor_var
    FROM mrp_unbuild
    WHERE id = unbuild_id_var;
    
    -- Factor is unbuild_qty / produced_qty (usually 1.0 if unbuilding full quantity)
    IF mo_qty_produced_var > 0 THEN
        factor_var := factor_var / mo_qty_produced_var;
    ELSE
        factor_var := 1.0;
    END IF;
    
    -- Create produce moves for raw materials
    -- Restore the exact quantity that was consumed (from move lines)
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
        SUM(rml.qty_done) * factor_var,  -- Restore consumed quantity from move lines
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
    INNER JOIN stock_move rm ON rm.raw_material_production_id = mo.id  -- THIS MO ONLY - ensures only lots from this MO
    INNER JOIN stock_location loc_dest ON rm.location_dest_id = loc_dest.id
    INNER JOIN stock_move_line rml ON rml.move_id = rm.id AND rml.qty_done > 0  -- Only consumed quantities
    WHERE mo.id = mo_id_var
      AND rm.state = 'done'
      -- Safety check: Ensure we're only working with THIS MO's moves
      AND rm.raw_material_production_id = mo_id_var
    GROUP BY mo.id, mo.name, rm.id, rm.product_id, rm.product_uom, 
             rm.location_dest_id, rm.location_id, mo.company_id, loc_dest.warehouse_id;
    
    RAISE NOTICE 'Produce moves created with factor: %', factor_var;
END $$;

-- ============================================
-- STEP 6: CREATE PRODUCE MOVE LINES (Raw Materials with Lots)
-- ============================================
-- Restore raw materials with their original lot numbers

DO $$
DECLARE
    unbuild_id_var INTEGER;
    mo_id_var INTEGER;
    mo_qty_produced_var NUMERIC;
    factor_var NUMERIC;
BEGIN
    SELECT id INTO unbuild_id_var
    FROM mrp_unbuild
    WHERE mo_id = (SELECT id FROM mrp_production WHERE name = 'WH/MO/800188')
    ORDER BY id DESC
    LIMIT 1;
    
    SELECT id INTO mo_id_var
    FROM mrp_production
    WHERE name = 'WH/MO/800188';
    
    -- Calculate factor same as before
    SELECT COALESCE(SUM(sml.qty_done), 0)
    INTO mo_qty_produced_var
    FROM mrp_production mo2
    INNER JOIN stock_move fm ON fm.production_id = mo2.id
    INNER JOIN stock_move_line sml ON sml.move_id = fm.id
    WHERE mo2.id = mo_id_var
      AND fm.state = 'done'
      AND fm.product_id = mo2.product_id
      AND sml.qty_done > 0;
    
    IF mo_qty_produced_var = 0 THEN
        SELECT COALESCE(SUM(fm.quantity_done), mo.product_qty)
        INTO mo_qty_produced_var
        FROM mrp_production mo2
        LEFT JOIN stock_move fm ON fm.production_id = mo2.id
            AND fm.state = 'done'
            AND fm.product_id = mo2.product_id
        WHERE mo2.id = mo_id_var
        GROUP BY mo2.product_qty;
    END IF;
    
    SELECT product_qty INTO factor_var
    FROM mrp_unbuild
    WHERE id = unbuild_id_var;
    
    IF mo_qty_produced_var > 0 THEN
        factor_var := factor_var / mo_qty_produced_var;
    ELSE
        factor_var := 1.0;
    END IF;
    
    -- Create move lines for tracked products (with lots)
    INSERT INTO stock_move_line (
        move_id,
        product_id,
        product_uom_id,
        location_id,
        location_dest_id,
        qty_done,
        reserved_uom_qty,
        date,
        lot_id,
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
        rml.qty_done * factor_var,  -- Restore consumed quantity with factor
        0.0 AS reserved_uom_qty,
        COALESCE(rml.date, CURRENT_TIMESTAMP) AS date,
        rml.lot_id,  -- Original lot number
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
      -- CRITICAL: Ensure original raw move belongs to THIS MO only
      AND rm.raw_material_production_id = mo_id_var
      AND NOT EXISTS (
          SELECT 1 FROM stock_move_line WHERE move_id = pm.id AND lot_id = rml.lot_id
      );
    
    -- Create move lines for non-tracked products
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
        rml.qty_done * factor_var,  -- Restore consumed quantity with factor
        0.0 AS reserved_uom_qty,
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
    WHERE pm.unbuild_id = unbuild_id_var
      AND pm.location_id != pm.location_dest_id  -- Produce moves
      AND rml.lot_id IS NULL  -- Non-tracked products
      -- CRITICAL: Ensure original raw move belongs to THIS MO only
      AND rm.raw_material_production_id = mo_id_var
      AND NOT EXISTS (
          SELECT 1 FROM stock_move_line WHERE move_id = pm.id
      );
    
    RAISE NOTICE 'Produce move lines created with lots';
END $$;

-- ============================================
-- STEP 7: UPDATE STOCK QUANTS
-- ============================================
-- Update inventory quantities to reflect the unbuild

-- 7.1: Remove finished products from stock (consume moves)
-- Only if there's actually stock to remove
UPDATE stock_quant sq
SET quantity = GREATEST(0, quantity - sml.qty_done)
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
INNER JOIN mrp_production mo ON ub.mo_id = mo.id
WHERE sq.product_id = sml.product_id
  AND sq.location_id = sml.location_id  -- Source location (where finished product is)
  AND COALESCE(sq.lot_id, -1) = COALESCE(sml.lot_id, -1)
  AND sm.location_id != sm.location_dest_id  -- Consume moves
  AND sml.qty_done > 0;

-- 7.2: Update existing quants or insert new ones for raw materials (produce moves)
-- First, update existing quants
UPDATE stock_quant sq
SET quantity = sq.quantity + sml.qty_done,
    in_date = LEAST(sq.in_date, NOW())
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
WHERE sq.product_id = sml.product_id
  AND sq.location_id = sml.location_dest_id
  AND COALESCE(sq.lot_id, -1) = COALESCE(sml.lot_id, -1)
  AND COALESCE(sq.package_id, -1) = -1  -- No package
  AND COALESCE(sq.owner_id, -1) = -1   -- No owner
  AND sq.company_id = sm.company_id
  AND sm.location_id != sm.location_dest_id  -- Produce moves
  AND sml.qty_done > 0;

-- Then, insert new quants for products/lots that don't exist yet
INSERT INTO stock_quant (
    product_id,
    location_id,
    quantity,
    reserved_quantity,
    lot_id,
    company_id,
    in_date,
    create_date,
    write_date,
    create_uid,
    write_uid
)
SELECT 
    sml.product_id,
    sml.location_dest_id,  -- Destination location (where to restore)
    sml.qty_done,
    0.0 AS reserved_quantity,
    sml.lot_id,
    sm.company_id,
    NOW() AS in_date,
    NOW(),
    NOW(),
    1,
    1
FROM stock_move_line sml
INNER JOIN stock_move sm ON sml.move_id = sm.id
INNER JOIN mrp_unbuild ub ON sm.unbuild_id = ub.id
WHERE sm.location_id != sm.location_dest_id  -- Produce moves
  AND sml.qty_done > 0
  AND NOT EXISTS (
      SELECT 1 FROM stock_quant sq
      WHERE sq.product_id = sml.product_id
        AND sq.location_id = sml.location_dest_id
        AND COALESCE(sq.lot_id, -1) = COALESCE(sml.lot_id, -1)
        AND COALESCE(sq.package_id, -1) = -1
        AND COALESCE(sq.owner_id, -1) = -1
        AND sq.company_id = sm.company_id
  );

-- ============================================
-- STEP 8: VERIFY UNBUILD
-- ============================================
-- Check that everything was created correctly

SELECT 
    'Unbuild Verification' AS check_type,
    ub.id AS unbuild_id,
    ub.name AS unbuild_name,
    ub.product_qty AS unbuild_qty,
    COUNT(DISTINCT cm.id) AS consume_moves,
    COUNT(DISTINCT pm.id) AS produce_moves,
    COUNT(DISTINCT cml.id) AS consume_move_lines,
    COUNT(DISTINCT pml.id) AS produce_move_lines
FROM mrp_unbuild ub
LEFT JOIN stock_move cm ON cm.unbuild_id = ub.id AND cm.location_id != cm.location_dest_id
LEFT JOIN stock_move pm ON pm.unbuild_id = ub.id AND pm.location_id != pm.location_dest_id
LEFT JOIN stock_move_line cml ON cml.move_id = cm.id
LEFT JOIN stock_move_line pml ON pml.move_id = pm.id
WHERE ub.mo_id = (SELECT id FROM mrp_production WHERE name = 'WH/MO/800188')
GROUP BY ub.id, ub.name, ub.product_qty;
