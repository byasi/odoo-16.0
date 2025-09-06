#!/usr/bin/env python3
"""
Script to update total_first_process for all existing purchase orders.
This script can be run from the Odoo shell or as a one-time update.

Usage:
1. From Odoo shell:
   python3 odoo-bin shell -d your_database_name
   >>> exec(open('addons/sales_move/scripts/update_total_first_process.py').read())

2. Or run this script directly in the Odoo environment
"""

def update_total_first_process():
    """
    Update total_first_process for all purchase orders in the system.
    """
    # Get the purchase order model
    purchase_orders = env['purchase.order']
    
    # Find all purchase orders
    all_orders = purchase_orders.search([])
    
    print(f"Found {len(all_orders)} purchase orders to update...")
    
    updated_count = 0
    for order in all_orders:
        try:
            # Force recomputation of the totals
            order._compute_totals()
            updated_count += 1
            
            if updated_count % 100 == 0:
                print(f"Updated {updated_count} orders...")
                
        except Exception as e:
            print(f"Error updating order {order.name}: {str(e)}")
            continue
    
    print(f"Successfully updated total_first_process for {updated_count} purchase orders.")
    
    # Commit the changes
    env.cr.commit()
    
    return updated_count

# Run the update
if __name__ == "__main__":
    update_total_first_process()
