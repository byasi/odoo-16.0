# MO-Specific Lot Restoration - Safety Measures

## Critical Requirement

**When unbuilding, we ONLY restore lot numbers that were consumed in THAT specific Manufacturing Order.**

This is critical because:
- A lot might be used in multiple MOs
- We should only restore the quantity consumed in THIS specific MO
- We must never restore lots that weren't used in this MO

## How the Scripts Ensure MO-Specific Restoration

### Primary Filter: `raw_material_production_id`

Both scripts use this critical join:
```sql
INNER JOIN stock_move rm ON rm.raw_material_production_id = mo.id
```

This ensures:
- ✅ Only stock moves that belong to THIS specific MO are included
- ✅ Only move lines from those moves are processed
- ✅ Only lots from those move lines are restored

### Safety Checks Added

1. **Verification Query (Step 0)**
   - Shows exactly which lots will be restored BEFORE running the script
   - Run this first to verify you're restoring the correct lots
   - Query filters by `rm.raw_material_production_id = mo.id`

2. **Explicit WHERE Clauses**
   - Added `AND rm.raw_material_production_id = mo_id_var` in critical sections
   - Double-checks that we're only working with THIS MO's moves

3. **Join Chain Verification**
   - The join chain ensures MO-specific filtering:
     ```
     mrp_production (mo) 
     → stock_move (rm.raw_material_production_id = mo.id) 
     → stock_move_line (rml.move_id = rm.id)
     → stock_lot (sl.id = rml.lot_id)
     ```

## Example Scenario

**Scenario**: Lot "LOT-001" was used in:
- MO-001: Consumed 10 units
- MO-002: Consumed 5 units

**When unbuilding MO-001**:
- ✅ Script will restore ONLY 10 units of LOT-001 (from MO-001)
- ❌ Script will NOT restore the 5 units from MO-002

**How it works**:
1. Script filters: `rm.raw_material_production_id = MO-001.id`
2. Only gets moves from MO-001
3. Only gets move lines from those moves
4. Only restores lots from those move lines
5. Result: Only 10 units restored (from MO-001)

## Verification Steps

### Before Running the Script

1. **Run Step 0 Verification Query**:
   ```sql
   -- Shows exactly which lots will be restored
   SELECT lot_id, lot_name, consumed_qty
   FROM ... WHERE mo.name = 'WH/MO/800188'
   ```
   - Verify the list matches what you expect
   - Check quantities are correct
   - Ensure no lots from other MOs appear

### After Running the Script

2. **Run Final Verification Query**:
   ```sql
   -- Shows which lots were actually restored
   SELECT lot_id, lot_name, restored_quantity, original_mo_name
   FROM ... WHERE mo.name = 'WH/MO/800188'
   ```
   - Verify only lots from THIS MO were restored
   - Check quantities match consumed quantities
   - Ensure `original_mo_id` matches the MO you unbuilt

## Code Locations

### In `unbuild_restore_from_consumed.sql`:

1. **Step 0**: Verification query (lines ~15-35)
2. **Step 1**: Consumed quantity calculation (line ~51)
   - `INNER JOIN stock_move rm ON rm.raw_material_production_id = mo2.id`
3. **Step 5**: Produce moves creation (line ~405)
   - `INNER JOIN stock_move rm ON rm.raw_material_production_id = mo.id`
   - `AND rm.raw_material_production_id = mo_id_var` (safety check)
4. **Step 6**: Move lines creation (lines ~474, ~518)
   - `AND rm.raw_material_production_id = mo_id_var` (safety check)
5. **Step 9**: Final verification (line ~620+)
   - `AND rm.raw_material_production_id = mo.id` (verification)

### In `unbuild_mo_corrected.sql`:

1. **Step 0**: Verification query (lines ~15-35)
2. **Step 1**: Consumed quantity calculation (line ~83)
   - `INNER JOIN stock_move rm ON rm.raw_material_production_id = mo2.id`
3. **Step 5**: Produce moves creation (line ~441)
   - `INNER JOIN stock_move rm ON rm.raw_material_production_id = mo.id`
   - `AND rm.raw_material_production_id = mo_id_var` (safety check)
4. **Step 6**: Move lines creation (lines ~576, ~620)
   - `AND rm.raw_material_production_id = mo_id_var` (safety check)

## Why This Matters

### Data Integrity
- Prevents accidentally restoring lots from wrong MOs
- Ensures inventory accuracy
- Maintains traceability

### Business Logic
- Each MO should only restore what it consumed
- Multiple MOs can use the same lot, but each restores independently
- Unbuilding one MO shouldn't affect another MO's lots

### Audit Trail
- Clear record of which MO restored which lots
- Verification queries show the relationship
- Easy to trace if issues arise

## Testing Checklist

Before running on production:

- [ ] Run Step 0 verification query
- [ ] Verify list of lots matches expectations
- [ ] Check quantities are correct
- [ ] Ensure no lots from other MOs appear
- [ ] Run the unbuild script
- [ ] Run final verification query
- [ ] Confirm only THIS MO's lots were restored
- [ ] Verify quantities match consumed quantities
- [ ] Check stock quants are updated correctly

## Common Mistakes to Avoid

1. **Don't remove the `raw_material_production_id` filter**
   - This is the primary safety mechanism
   - Removing it would restore lots from ALL MOs

2. **Don't use generic lot queries**
   - Always filter by MO first
   - Then get lots from that MO's moves

3. **Don't skip verification queries**
   - Always run Step 0 before unbuild
   - Always run final verification after unbuild

## Summary

Both scripts are now **explicitly designed** to:
- ✅ Only restore lots from the specific MO being unbuilt
- ✅ Filter by `raw_material_production_id` at every step
- ✅ Include verification queries to confirm MO-specific restoration
- ✅ Add safety checks to prevent accidental cross-MO restoration

**The scripts are safe to use and will only restore lots from the specified Manufacturing Order.**
