#!/usr/bin/env python3
"""
Odoo Script to Undo Manufacturing Order Lot Consumption
========================================================
This script uses Odoo's API to safely reverse lot consumption
from a manufacturing order that was confirmed by mistake.

Usage:
    python3 undo_mrp_consumption.py

Make sure to configure your Odoo connection settings below.
"""

import xmlrpc.client
import sys

# ============================================
# CONFIGURATION - Update these values
# ============================================
ODOO_URL = 'http://localhost:8069'
ODOO_DB = 'your_database_name'
ODOO_USERNAME = 'admin'
ODOO_PASSWORD = 'admin'
MO_NAME = 'WH/MO/800179'  # Replace with your manufacturing order name

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
# MAIN FUNCTIONS
# ============================================
def check_mo_state(uid, models, mo_name):
    """Check the current state of the manufacturing order"""
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
    
    # Check stock moves
    move_ids = mo_data['move_raw_ids'] + mo_data['move_finished_ids']
    if move_ids:
        moves = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'stock.move', 'read',
            [move_ids],
            {'fields': ['id', 'state', 'product_id', 'quantity_done']}
        )
        
        done_moves = [m for m in moves if m['state'] == 'done']
        active_moves = [m for m in moves if m['state'] not in ('done', 'cancel')]
        
        print(f"\nStock Moves:")
        print(f"  Total: {len(moves)}")
        print(f"  Done: {len(done_moves)}")
        print(f"  Active (can cancel): {len(active_moves)}")
        
        if done_moves:
            print(f"\n⚠ WARNING: {len(done_moves)} move(s) are already 'done'.")
            print("   Reversing these may require creating reverse moves.")
    
    return mo_data

def view_consumed_lots(uid, models, mo_name):
    """View all consumed lot numbers"""
    mo_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'mrp.production', 'search',
        [[('name', '=', mo_name)]]
    )
    
    if not mo_ids:
        return
    
    # Get all raw material moves
    move_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move', 'search',
        [[('raw_material_production_id', '=', mo_ids[0])]]
    )
    
    if not move_ids:
        print("\nNo raw material moves found.")
        return
    
    # Get move lines with lots
    move_line_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move.line', 'search',
        [[('move_id', 'in', move_ids), ('qty_done', '>', 0)]]
    )
    
    if not move_line_ids:
        print("\nNo consumed lots found.")
        return
    
    move_lines = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move.line', 'read',
        [move_line_ids],
        {'fields': ['lot_id', 'product_id', 'qty_done', 'location_id', 'location_dest_id']}
    )
    
    print(f"\n{'='*60}")
    print(f"Consumed Lots Summary")
    print(f"{'='*60}")
    print(f"{'Lot Name':<20} {'Product':<30} {'Qty Consumed':<15}")
    print(f"{'-'*60}")
    
    total_qty = 0
    for ml in move_lines:
        if ml['lot_id']:
            lot = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'stock.lot', 'read',
                [[ml['lot_id'][0]]],
                {'fields': ['name']}
            )[0]
            
            product = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'product.product', 'read',
                [[ml['product_id'][0]]],
                {'fields': ['name']}
            )[0]
            
            qty = ml['qty_done']
            total_qty += qty
            print(f"{lot['name']:<20} {product['name'][:30]:<30} {qty:<15}")
    
    print(f"{'-'*60}")
    print(f"Total Quantity Consumed: {total_qty}")
    print(f"{'='*60}")

def cancel_mo_if_possible(uid, models, mo_name):
    """Cancel manufacturing order if moves are not done"""
    mo_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'mrp.production', 'search',
        [[('name', '=', mo_name)]]
    )
    
    if not mo_ids:
        print(f"ERROR: Manufacturing order '{mo_name}' not found!")
        return False
    
    # Check if any moves are done
    move_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move', 'search',
        [[('raw_material_production_id', '=', mo_ids[0])]]
    )
    
    if move_ids:
        moves = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'stock.move', 'read',
            [move_ids],
            {'fields': ['state']}
        )
        
        done_moves = [m for m in moves if m['state'] == 'done']
        if done_moves:
            print(f"\n⚠ Cannot cancel: {len(done_moves)} move(s) are already 'done'.")
            print("   You need to reverse the moves first.")
            return False
    
    # Cancel the manufacturing order
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'mrp.production', 'action_cancel',
            [mo_ids]
        )
        print(f"\n✓ Successfully cancelled manufacturing order: {mo_name}")
        return True
    except Exception as e:
        print(f"\n✗ Error cancelling manufacturing order: {e}")
        return False

def reset_move_line_qty_done(uid, models, mo_name):
    """Reset qty_done to 0 for move lines (reverses consumption)"""
    mo_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'mrp.production', 'search',
        [[('name', '=', mo_name)]]
    )
    
    if not mo_ids:
        print(f"ERROR: Manufacturing order '{mo_name}' not found!")
        return False
    
    # Get all raw material moves
    move_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move', 'search',
        [[('raw_material_production_id', '=', mo_ids[0])]]
    )
    
    if not move_ids:
        print("No raw material moves found.")
        return False
    
    # Get move lines with qty_done > 0
    move_line_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.move.line', 'search',
        [[('move_id', 'in', move_ids), ('qty_done', '>', 0)]]
    )
    
    if not move_line_ids:
        print("No consumed quantities found to reset.")
        return False
    
    # Reset qty_done to 0
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'stock.move.line', 'write',
            [move_line_ids, {'qty_done': 0}]
        )
        print(f"\n✓ Successfully reset qty_done for {len(move_line_ids)} move line(s)")
        print("  Note: You may need to update stock quants manually or use inventory adjustments")
        return True
    except Exception as e:
        print(f"\n✗ Error resetting qty_done: {e}")
        return False

# ============================================
# MAIN EXECUTION
# ============================================
def main():
    print("="*60)
    print("Odoo Manufacturing Order - Undo Lot Consumption")
    print("="*60)
    
    # Connect to Odoo
    uid, models = connect_to_odoo()
    
    # Check current state
    mo_data = check_mo_state(uid, models, MO_NAME)
    if not mo_data:
        return
    
    # View consumed lots
    view_consumed_lots(uid, models, MO_NAME)
    
    # Ask user what to do
    print("\n" + "="*60)
    print("Options:")
    print("1. Cancel MO (if moves are not done)")
    print("2. Reset qty_done to 0 (reverses consumption)")
    print("3. Exit")
    print("="*60)
    
    choice = input("\nEnter your choice (1-3): ").strip()
    
    if choice == '1':
        confirm = input(f"\n⚠ Are you sure you want to cancel MO '{MO_NAME}'? (yes/no): ")
        if confirm.lower() == 'yes':
            cancel_mo_if_possible(uid, models, MO_NAME)
        else:
            print("Cancelled.")
    elif choice == '2':
        confirm = input(f"\n⚠ This will reset qty_done to 0. Continue? (yes/no): ")
        if confirm.lower() == 'yes':
            reset_move_line_qty_done(uid, models, MO_NAME)
        else:
            print("Cancelled.")
    else:
        print("Exiting...")

if __name__ == '__main__':
    main()
