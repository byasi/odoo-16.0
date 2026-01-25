# Unbuild Approaches Comparison

## Two Different Approaches

### Approach 1: `unbuild_mo_corrected.sql`
**Restores based on PRODUCED quantity (finished product)**

- Uses finished product quantity to calculate what to unbuild
- Restores raw materials proportionally based on what was produced
- Follows Odoo's standard unbuild logic
- **Problem**: If `total_produced_qty` is 0.0, it falls back to planned quantity (which may be wrong)

### Approach 2: `unbuild_restore_from_consumed.sql` ⭐ **RECOMMENDED FOR YOUR CASE**
**Restores based on CONSUMED quantities (raw materials)**

- Uses raw material consumed quantities directly
- Restores EXACTLY what was consumed, regardless of what was produced
- Doesn't rely on finished product quantities
- **Best for**: When finished product quantities are not properly recorded

## Key Differences

| Aspect | Corrected Script | Restore From Consumed |
|--------|-----------------|----------------------|
| **Quantity Source** | Finished product moves/lines | Raw material moves/lines |
| **Calculation** | Produced qty → factor → restore | Direct consumed qty → restore |
| **Works when produced qty = 0?** | ❌ Falls back to planned (may be wrong) | ✅ Yes, uses consumed qty |
| **Works when consumed qty = 0?** | ✅ Yes (if produced qty exists) | ❌ No (nothing to restore) |
| **Accuracy** | Proportional to production | Exact match to consumption |
| **Use Case** | Normal unbuild scenarios | When production records are incomplete |

## For Your Situation

Based on your diagnostic output:
- `mo_planned_qty`: 2053.9
- `total_produced_qty`: **0.0** ⚠️
- `available_in_stock`: 4107.8
- `unbuild_qty`: 0.0

**Recommendation**: Use `unbuild_restore_from_consumed.sql` because:
1. ✅ Your `total_produced_qty` is 0.0, so the corrected script would use planned quantity (not ideal)
2. ✅ You want to restore raw materials based on what was actually consumed
3. ✅ This approach doesn't depend on finished product quantities
4. ✅ It restores exactly what was consumed, which is what you need

## How Each Script Works

### `unbuild_mo_corrected.sql` Flow:
```
1. Get produced quantity from finished moves/lines
2. If 0, fall back to planned quantity
3. Calculate factor = unbuild_qty / produced_qty
4. Restore raw materials = consumed_qty × factor
```

### `unbuild_restore_from_consumed.sql` Flow:
```
1. Get consumed quantities from raw material moves/lines
2. Restore EXACTLY those quantities
3. No factor calculation needed
4. Direct 1:1 restoration
```

## Example

**Scenario**: 
- Planned: 100 units
- Consumed: 50 units of raw material A, 30 units of raw material B
- Produced: 0 units (not recorded properly)

**Corrected Script**:
- Would use planned qty (100) or 0
- Would restore: 50 × (100/0) = ERROR or 50 × (100/100) = 50 ❌

**Restore From Consumed Script**:
- Uses consumed quantities directly
- Would restore: 50 units of A, 30 units of B ✅

## When to Use Which

### Use `unbuild_mo_corrected.sql` when:
- ✅ Finished product quantities are properly recorded
- ✅ You want standard Odoo unbuild behavior
- ✅ You need proportional restoration based on production

### Use `unbuild_restore_from_consumed.sql` when:
- ✅ Finished product quantities are missing/incorrect (your case)
- ✅ You want to restore exactly what was consumed
- ✅ You don't care about finished product quantities
- ✅ You just want the raw materials back

## Verification

After running `unbuild_restore_from_consumed.sql`, verify:

1. **Check restored lots**:
   ```sql
   -- Run the verification query at the end of the script
   -- Should show all lots with their restored quantities
   ```

2. **Check stock quants**:
   ```sql
   SELECT * FROM stock_quant 
   WHERE lot_id IN (
       SELECT lot_id FROM stock_move_line 
       WHERE move_id IN (
           SELECT id FROM stock_move WHERE unbuild_id = <unbuild_id>
       )
   );
   ```

3. **Check unbuild order**:
   ```sql
   SELECT * FROM mrp_unbuild WHERE mo_id = <mo_id>;
   ```

## Important Notes

1. **Consume Moves**: The "restore from consumed" script only creates consume moves for finished products if they exist in stock. If not, it skips them and just restores raw materials.

2. **Unbuild Order Quantity**: The unbuild order will still have a quantity (produced or planned), but the actual restoration is based on consumed quantities.

3. **Data Consistency**: Both scripts maintain data consistency, but the "restore from consumed" approach is more direct and doesn't require finished product quantities.

4. **Lots**: Both scripts properly restore lots with their original lot numbers.

## Recommendation for Your Case

**Use `unbuild_restore_from_consumed.sql`** because:
- Your `total_produced_qty` is 0.0
- You want to restore raw materials based on consumed quantities
- It's more reliable when production records are incomplete
- It restores exactly what was consumed, which is what you need
