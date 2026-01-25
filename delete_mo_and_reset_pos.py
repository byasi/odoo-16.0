#!/usr/bin/env python3
"""
Odoo Script to Delete Manufacturing Order and Reset Purchase Orders
====================================================================
This script safely deletes a manufacturing order and all associated lots,
then resets the purchase orders to allow re-receiving products.

WARNING: This is a destructive operation! Backup your database first!

Usage:
    python3 delete_mo_and_reset_pos.py

Make sure to configure your Odoo connection settings below.
"""

import xmlrpc.client
import sys
from collections import defaultdict

# ============================================
# CONFIGURATION - Update these values
# ============================================
ODOO_URL = 'http://localhost:8069'
ODOO_DB = 'your_database_name'
ODOO_USERNAME = 'admin'
ODOO_PASSWORD = 'admin'
MO_NAME = 'WH/MO/800188'  # Replace with your manufacturing order name

# ============================================
# CONNECT TO ODOO
# ============================================
def connect_to_odoo():
    """Connect to Odoo and return uid and models"""
    try:
        common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common')
        uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})
        
        if not uid:
            print("ERROR: Authentication failed!")
            sys.exit(1)
        
        models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object')
        print(f"✓ Connected to Odoo database: {ODOO_DB}")
        return uid, models
    except Exception as e:
        print(f"ERROR: Failed to connect to Odoo: {e}")
        sys.exit(1)

# ============================================
# DIAGNOSTIC FUNCTIONS
# ============================================
def analyze_mo(uid, models, mo_name):
    """Analyze the manufacturing order and show what will be affected"""
    print("\n" + "="*60)
    print("ANALYZING MANUFACTURING ORDER")
    print("="*60)
    
    # Find MO
    mo_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'mrp.production', 'search',
        [[('name', '=', mo_name)]]
    )
    
    if not mo_ids:
        print(f"ERROR: Manufacturing order '{mo_name}' not found!")
        return None
    
    mo_data = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'mrp.production', 'read',
        [mo_ids],
        {'fields': ['id', 'name', 'state', 'move_raw_ids', 'move_finished_ids']}
    )[0]
    
    print(f"\nManufacturing Order: {mo_data['name']}")
    print(f"State: {mo_data['state']}")
    print(f"ID: {mo_data['id']}")
    
    # Get stock moves
    move_ids = mo_data['move_raw_ids']
    if move_ids:
        moves = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'stock.move', 'read',
            [move_ids],
            {'fields': ['id', 'state', 'product_id', 'move_line_ids']}
        )
        
        print(f"\nStock Moves (Raw Materials): {len(moves)}")
        for move in moves:
            print(f"  - Move ID {move['id']}: State = {move['state']}")
        
        # Get move lines with lots
        all_move_line_ids = []
        for move in moves:
            all_move_line_ids.extend(move['move_line_ids'])
        
        if all_move_line_ids:
            move_lines = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'stock.move.line', 'read',
                [all_move_line_ids],
                {'fields': ['id', 'lot_id', 'qty_done', 'product_id']}
            )
            
            lots_used = set()
            for ml in move_lines:
                if ml['lot_id'] and ml['qty_done'] > 0:
                    lots_used.add(ml['lot_id'][0])
            
            print(f"\nLots Used: {len(lots_used)}")
            if lots_used:
                lots = models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    'stock.lot', 'read',
                    [list(lots_used)],
                    {'fields': ['id', 'name']}
                )
                for lot in lots:
                    print(f"  - Lot: {lot['name']} (ID: {lot['id']})")
                
                # Find purchase orders
                find_purchase_orders(uid, models, list(lots_used))
    
    return mo_data

def find_purchase_orders(uid, models, lot_ids):
    """Find purchase orders that created these lots"""
    print(f"\nFinding Purchase Orders...")
    
    # Find move lines with these lots from purchase receipts
    move_line_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move.line', 'search',
        [[('lot_id', 'in', lot_ids), ('qty_done', '>', 0)]]
    )
    
    if not move_line_ids:
        print("  No purchase order receipts found for these lots.")
        return []
    
    move_lines = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move.line', 'read',
        [move_line_ids],
        {'fields': ['move_id', 'lot_id']}
    )
    
    move_ids = list(set([ml['move_id'][0] for ml in move_lines]))
    
    moves = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move', 'read',
        [move_ids],
        {'fields': ['id', 'picking_id', 'location_id']}
    )
    
    # Filter for incoming moves (from supplier)
    picking_ids = []
    for move in moves:
        picking_id = move.get('picking_id')
        if picking_id:
            picking_ids.append(picking_id[0])
    
    if not picking_ids:
        print("  No purchase pickings found.")
        return []
    
    pickings = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.picking', 'read',
        [picking_ids],
        {'fields': ['id', 'name', 'state', 'purchase_id']}
    )
    
    po_ids = []
    for picking in pickings:
        po_id = picking.get('purchase_id')
        if po_id:
            po_ids.append(po_id[0])
    
    if not po_ids:
        print("  No purchase orders found.")
        return []
    
    pos = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'purchase.order', 'read',
        [list(set(po_ids))],
        {'fields': ['id', 'name', 'state']}
    )
    
    print(f"\nPurchase Orders Found: {len(pos)}")
    for po in pos:
        print(f"  - PO: {po['name']} (ID: {po['id']}, State: {po['state']})")
    
    return pos

# ============================================
# DELETION FUNCTIONS
# ============================================
def delete_manufacturing_order(uid, models, mo_name):
    """Delete the manufacturing order and all related data"""
    print("\n" + "="*60)
    print("DELETING MANUFACTURING ORDER")
    print("="*60)
    
    # Find MO
    mo_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'mrp.production', 'search',
        [[('name', '=', mo_name)]]
    )
    
    if not mo_ids:
        print(f"ERROR: Manufacturing order '{mo_name}' not found!")
        return False
    
    mo_data = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'mrp.production', 'read',
        [mo_ids],
        {'fields': ['id', 'name', 'state']}
    )[0]
    
    if mo_data['state'] == 'done':
        print(f"\n⚠ WARNING: MO is in 'done' state. Cannot delete directly.")
        print("   Attempting to cancel first...")
        try:
            models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'mrp.production', 'action_cancel',
                [mo_ids]
            )
            print("   ✓ MO cancelled")
        except Exception as e:
            print(f"   ✗ Error cancelling MO: {e}")
            return False
    
    # Get all related moves
    move_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move', 'search',
        [[('raw_material_production_id', '=', mo_ids[0])]]
    )
    
    # Reset move line quantities
    if move_ids:
        move_line_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'stock.move.line', 'search',
            [[('move_id', 'in', move_ids), ('qty_done', '>', 0)]]
        )
        
        if move_line_ids:
            try:
                models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    'stock.move.line', 'write',
                    [move_line_ids, {'qty_done': 0}]
                )
                print(f"   ✓ Reset qty_done for {len(move_line_ids)} move lines")
            except Exception as e:
                print(f"   ✗ Error resetting move lines: {e}")
    
    # Cancel moves
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'stock.move', 'write',
            [move_ids, {'state': 'cancel'}]
        )
        print(f"   ✓ Cancelled {len(move_ids)} stock moves")
    except Exception as e:
        print(f"   ✗ Error cancelling moves: {e}")
    
    # Delete work orders
    workorder_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'mrp.workorder', 'search',
        [[('production_id', '=', mo_ids[0])]]
    )
    
    if workorder_ids:
        try:
            models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'mrp.workorder', 'unlink',
                [workorder_ids]
            )
            print(f"   ✓ Deleted {len(workorder_ids)} work orders")
        except Exception as e:
            print(f"   ✗ Error deleting work orders: {e}")
    
    # Delete MO
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'mrp.production', 'unlink',
            [mo_ids]
        )
        print(f"   ✓ Deleted manufacturing order: {mo_name}")
        return True
    except Exception as e:
        print(f"   ✗ Error deleting MO: {e}")
        return False

def delete_lots(uid, models, mo_name):
    """Delete lots that were only used in this MO"""
    print("\n" + "="*60)
    print("DELETING LOTS")
    print("="*60)
    
    # Find lots used in MO
    mo_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'mrp.production', 'search',
        [[('name', '=', mo_name)]]
    )
    
    if not mo_ids:
        return []
    
    move_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move', 'search',
        [[('raw_material_production_id', '=', mo_ids[0])]]
    )
    
    if not move_ids:
        return []
    
    move_line_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move.line', 'search',
        [[('move_id', 'in', move_ids), ('lot_id', '!=', False), ('qty_done', '>', 0)]]
    )
    
    if not move_line_ids:
        print("   No lots found to delete")
        return []
    
    move_lines = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move.line', 'read',
        [move_line_ids],
        {'fields': ['lot_id']}
    )
    
    lot_ids = list(set([ml['lot_id'][0] for ml in move_lines if ml['lot_id']]))
    
    # Check if lots are used elsewhere
    safe_to_delete = []
    for lot_id in lot_ids:
        # Check if lot is used in other MOs
        other_move_line_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'stock.move.line', 'search',
            [[('lot_id', '=', lot_id), ('id', 'not in', move_line_ids), ('qty_done', '>', 0)]]
        )
        
        if not other_move_line_ids:
            safe_to_delete.append(lot_id)
        else:
            lot = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'stock.lot', 'read',
                [[lot_id]],
                {'fields': ['name']}
            )[0]
            print(f"   ⚠ Skipping lot {lot['name']} - used elsewhere")
    
    if safe_to_delete:
        lots = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'stock.lot', 'read',
            [safe_to_delete],
            {'fields': ['name']}
        )
        
        try:
            models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'stock.lot', 'unlink',
                [safe_to_delete]
            )
            print(f"   ✓ Deleted {len(safe_to_delete)} lot(s)")
            for lot in lots:
                print(f"     - {lot['name']}")
        except Exception as e:
            print(f"   ✗ Error deleting lots: {e}")
    
    return safe_to_delete

def reset_purchase_orders(uid, models, lot_ids):
    """Reset purchase orders to allow re-receiving"""
    print("\n" + "="*60)
    print("RESETTING PURCHASE ORDERS")
    print("="*60)
    
    if not lot_ids:
        print("   No lots provided")
        return
    
    # Find purchase orders
    move_line_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move.line', 'search',
        [[('lot_id', 'in', lot_ids), ('qty_done', '>', 0)]]
    )
    
    if not move_line_ids:
        print("   No purchase receipts found")
        return
    
    move_lines = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move.line', 'read',
        [move_line_ids],
        {'fields': ['move_id']}
    )
    
    move_ids = list(set([ml['move_id'][0] for ml in move_lines]))
    
    moves = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move', 'read',
        [move_ids],
        {'fields': ['id', 'picking_id', 'location_id']}
    )
    
    # Get pickings from supplier locations
    picking_ids = []
    for move in moves:
        picking_id = move.get('picking_id')
        if picking_id:
            picking_ids.append(picking_id[0])
    
    if not picking_ids:
        print("   No purchase pickings found")
        return
    
    pickings = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.picking', 'read',
        [picking_ids],
        {'fields': ['id', 'name', 'state', 'purchase_id']}
    )
    
    po_ids = []
    for picking in pickings:
        po_id = picking.get('purchase_id')
        if po_id:
            po_ids.append(po_id[0])
    
    if not po_ids:
        print("   No purchase orders found")
        return
    
    po_ids = list(set(po_ids))
    
    # Cancel pickings
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'stock.picking', 'action_cancel',
            [picking_ids]
        )
        print(f"   ✓ Cancelled {len(picking_ids)} purchase pickings")
    except Exception as e:
        print(f"   ✗ Error cancelling pickings: {e}")
    
    # Reset purchase order lines
    pol_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'purchase.order.line', 'search',
        [[('order_id', 'in', po_ids)]]
    )
    
    if pol_ids:
        try:
            models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'purchase.order.line', 'write',
                [pol_ids, {'qty_received': 0, 'qty_received_manual': 0}]
            )
            print(f"   ✓ Reset qty_received for {len(pol_ids)} purchase order lines")
        except Exception as e:
            print(f"   ✗ Error resetting PO lines: {e}")
    
    # Reset PO state
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'purchase.order', 'write',
            [po_ids, {'state': 'purchase'}]
        )
        print(f"   ✓ Reset {len(po_ids)} purchase order(s) to 'purchase' state")
        print("   You can now click 'Receive Products' again to create new lots")
    except Exception as e:
        print(f"   ✗ Error resetting PO state: {e}")

# ============================================
# MAIN EXECUTION
# ============================================
def main():
    print("="*60)
    print("DELETE MANUFACTURING ORDER AND RESET PURCHASE ORDERS")
    print("="*60)
    print("\n⚠ WARNING: This is a destructive operation!")
    print("   Make sure you have backed up your database!")
    
    # Connect to Odoo
    uid, models = connect_to_odoo()
    
    # Analyze first
    mo_data = analyze_mo(uid, models, MO_NAME)
    if not mo_data:
        return
    
    # Confirm
    print("\n" + "="*60)
    confirm = input(f"\n⚠ Are you sure you want to delete MO '{MO_NAME}' and reset POs? (yes/no): ")
    if confirm.lower() != 'yes':
        print("Operation cancelled.")
        return
    
    # Execute deletion
    print("\nStarting deletion process...")
    
    # Step 1: Delete lots (get IDs first)
    lot_ids = []
    mo_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'mrp.production', 'search',
        [[('name', '=', MO_NAME)]]
    )
    if mo_ids:
        move_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'stock.move', 'search',
            [[('raw_material_production_id', '=', mo_ids[0])]]
        )
        if move_ids:
            move_line_ids = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'stock.move.line', 'search',
                [[('move_id', 'in', move_ids), ('lot_id', '!=', False), ('qty_done', '>', 0)]]
            )
            if move_line_ids:
                move_lines = models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    'stock.move.line', 'read',
                    [move_line_ids],
                    {'fields': ['lot_id']}
                )
                lot_ids = list(set([ml['lot_id'][0] for ml in move_lines if ml['lot_id']]))
    
    # Step 2: Delete MO
    delete_manufacturing_order(uid, models, MO_NAME)
    
    # Step 3: Delete lots
    deleted_lot_ids = delete_lots(uid, models, MO_NAME)
    
    # Step 4: Reset purchase orders
    if lot_ids:
        reset_purchase_orders(uid, models, lot_ids)
    
    print("\n" + "="*60)
    print("DELETION COMPLETE")
    print("="*60)
    print("\n✓ Manufacturing order deleted")
    print("✓ Lots deleted")
    print("✓ Purchase orders reset - you can now receive products again")

if __name__ == '__main__':
    main()
