# Unbuild Quantity Issue - Explanation and Fix

## The Problem

### Issue 1: Quantity Calculation Error
The original SQL unbuild script was showing `0.00` quantity in the unbuild order because:
- It was using `SUM(fm.quantity_done)` from the `stock_move` table
- However, `quantity_done` on the move might be 0 or NULL
- The actual quantity is stored in `stock_move_line.qty_done` (the move lines)

### Issue 2: UI Validation vs SQL Bypass
- **In the UI**: Odoo checks if finished product is available in stock using `_get_available_quantity()`
- If you enter the quantity consumed (total done quantity of lot numbers), but the finished product is not in stock, it shows: **"Insufficient Quantity To Unbuild - the product is not available in sufficient Quantity in WH/Stock"**
- **In the SQL script**: We bypassed this check and created moves anyway, which could cause inconsistencies

### Issue 3: Wrong Quantity Source
- The user was entering the **quantity consumed** (raw materials)
- But unbuild needs the **quantity produced** (finished product)
- These might be different if there was waste, byproducts, or partial production

## The Solution

### Corrected Script: `unbuild_mo_corrected.sql`

The corrected script now:

1. **Calculates quantity from move lines** (not just moves):
   ```sql
   SELECT COALESCE(SUM(sml.qty_done), 0)
   FROM stock_move_line sml
   INNER JOIN stock_move fm ON sml.move_id = fm.id
   WHERE fm.production_id = mo.id
     AND fm.state = 'done'
     AND fm.product_id = mo.product_id
     AND sml.qty_done > 0
   ```

2. **Checks available stock** (for information, but doesn't block):
   - Warns if finished product is not in stock
   - Still restores raw materials (which is the goal)

3. **Uses actual consumed quantities** for raw materials:
   - Restores exactly what was consumed from `stock_move_line.qty_done`
   - Applies the correct factor if unbuilding partial quantity

4. **Properly handles lots**:
   - Restores raw materials with their original lot numbers
   - Handles both tracked and non-tracked products

## How to Use

### Step 1: Diagnose the Issue
Run `diagnose_unbuild_quantity.sql` to check:
- What quantity was produced
- What quantity is available in stock
- What the unbuild order shows
- What quantities are in move lines vs moves

### Step 2: Run Corrected Unbuild
Run `unbuild_mo_corrected.sql` which will:
- Properly calculate quantities from move lines
- Create unbuild order with correct quantity
- Restore raw materials with correct lots
- Update stock quants correctly

### Step 3: Verify
Check that:
- Unbuild order shows correct quantity (not 0.00)
- Raw material lots are restored
- Stock quants are updated correctly

## Key Differences

| Aspect | Original Script | Corrected Script |
|--------|----------------|------------------|
| Quantity Source | `fm.quantity_done` (move) | `sml.qty_done` (move lines) |
| Stock Check | None | Warns if not in stock |
| Quantity Calculation | Single query | Multiple fallbacks |
| Lot Restoration | Basic | Properly handles all cases |
| Error Handling | Minimal | Validates quantities |

## Important Notes

1. **Quantity to Unbuild**: Should be the **quantity produced** (finished product), not the quantity consumed (raw materials)

2. **If Finished Product Not in Stock**: 
   - The corrected script will still restore raw materials
   - The consume move for finished product will have 0 quantity (or the available quantity)
   - This is acceptable since the goal is to restore raw materials

3. **Data Consistency**: 
   - The corrected script ensures quantities match between:
     - Unbuild order `product_qty`
     - Consume move `product_uom_qty`
     - Produce move `product_uom_qty`
     - Move lines `qty_done`
     - Stock quants `quantity`

## Why the UI Shows Error

The UI error "Insufficient Quantity To Unbuild" happens because:
1. You're trying to unbuild a quantity that's not available in stock
2. The finished product might have been:
   - Sold
   - Moved to another location
   - Already unbuilt
   - Never actually put into stock

The SQL script bypasses this check because:
- We're restoring raw materials, not necessarily consuming finished products
- We can create the moves directly without validation
- We handle the case where finished product is not in stock

## Recommendation

1. **First**: Run `diagnose_unbuild_quantity.sql` to understand the current state
2. **Then**: Run `unbuild_mo_corrected.sql` to properly restore the lots
3. **Finally**: Verify using the queries in `verify_unbuild_and_check_lots.sql`

The corrected script ensures data consistency and properly calculates all quantities from the source of truth: `stock_move_line.qty_done`.
