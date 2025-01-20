from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import math
from datetime import datetime

class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    weighted_average_quality = fields.Float(
        string="Product Quality",
        compute="_compute_weighted_average_quality",
        store=True
    )
    # product_quality = fields.Float(string="Product Quality", store=True)
    lot_product_quality = fields.Float(string="Product Quality", compute="_compute_lot_product_quality", store=True)  # from Inventory
    lot_first_process_wt = fields.Float(string="First Process Wt", compute="_compute_lot_first_process_wt", store=True) # from Inventory
    lot_purchase_cost = fields.Float(string="Purchase Cost", compute="_compute_lot_purchase_cost", store=True)
    mo_product_quality = fields.Float(string="Product Quality ", compute="_fetch_lot_values", store=True)  # from  manufacturing
    mo_first_process_wt = fields.Float(string="First Process Wt", compute="_fetch_lot_values", store=True) # from manufacturing
    mo_purchase_cost = fields.Float(string="Purchase Cost", compute="_fetch_lot_values", store=True)
    qty_done = fields.Float(string="Done Quantity", compute="_compute_qty_done", store=True)
    product_quantity = fields.Float(string="Product Quantity", compute="_compute_product_quantity", store=True)
    average_product_quality = fields.Float(string="Product Quality", compute="_compute_product_quantity", store=True)
    product_cost = fields.Float(string="Product Cost", compute="_compute_product_quantity", store=True)
    lot_name = fields.Char(string="Lot Name", copy=False)

    @api.model
    def create(self, vals):
        if not vals.get('lot_name'):
            today = datetime.today()
            date_prefix = today.strftime('%d%b%y').upper()  # e.g., 20JAN25
            # Find the highest sequence for the current date prefix
            last_lot = self.search([('lot_name', 'like', f"{date_prefix}-%")], order="lot_name desc", limit=1)
            if last_lot:
                # Extract and increment the sequence number
                last_sequence = int(last_lot.lot_name.split('-')[-1])
                new_sequence = f"{last_sequence + 1:03d}"
            else:
                # Start the sequence at 001 if no lots exist for the day
                new_sequence = "001"
            # Generate the lot name
            vals['lot_name'] = f"{date_prefix}-{new_sequence}"
        return super(StockMoveLine, self).create(vals)

    @api.constrains('lot_name')
    def _check_lot_name_unique(self):
        for record in self:
            if record.lot_name:
                # Search for existing lots with the same name
                existing_lots = self.search([
                    ('lot_name', '=', record.lot_name),
                    ('id', '!=', record.id)  # Exclude the current record from the search
                ])
                if existing_lots:
                    raise ValidationError(_(
                        "The Lot Name '%s' already exists. Please choose a different name." % record.lot_name
                    ))

    @api.depends('move_id.product_quality')
    def _compute_lot_product_quality(self):
        for line in self:
            line.lot_product_quality = line.move_id.product_quality

    @api.depends('move_id.first_process_wt')
    def _compute_lot_first_process_wt(self):
        for line in self:
            line.lot_first_process_wt = line.move_id.first_process_wt

    @api.depends('move_id.purchase_cost')
    def _compute_lot_purchase_cost(self):
        for line in self:
            line.lot_purchase_cost = line.move_id.purchase_cost

    @api.depends('lot_id')
    def _fetch_lot_values(self):
        for line in self:
            if line.lot_id and line.lot_id.name:
                # Fetch the first record with the matching lot name
                matching_line = self.search([('lot_id.name', '=', line.lot_id.name)], limit=1)
                if matching_line:
                    # Set the values only if matching_line is found
                    line.mo_product_quality = matching_line.lot_product_quality
                    line.mo_first_process_wt = matching_line.lot_first_process_wt
                    line.mo_purchase_cost = matching_line.lot_purchase_cost
                else:
                    # If no matching line is found, set to 0.0
                    line.mo_product_quality = 0.0
                    line.mo_first_process_wt = 0.0
                    line.mo_purchase_cost = 0.0
            else:
                line.mo_product_quality = 0.0
                line.mo_first_process_wt = 0.0
                line.mo_purchase_cost = 0.0




    @api.depends('move_id.product_uom_qty', 'mo_first_process_wt', 'move_id.picking_type_id')
    def _compute_qty_done(self):
        if self.env.context.get('skip_fetch_lot_values'):
            return
        for line in self:
            if line.move_id.picking_type_id and line.move_id.picking_type_id.code == 'mrp_operation':
                line.qty_done = line.mo_first_process_wt or 0.0
                # print(f'Mo_process_wt {line.mo_first_process_wt}')
                # print(f'Product Quality {line.mo_product_quality}')
                # print(f'QTY_DONE {line.qty_done}')
            elif line.move_id.picking_type_id.code == 'outgoing':
                line.qty_done = line.product_quantity or 0.0
                # line.reserved_uom_qty = line.qty_done
            else:
                line.qty_done = line.move_id.product_uom_qty
                print(f"Product_uom_qty {line.move_id.product_uom_qty}")

    @api.depends('lot_id')
    def _compute_weighted_average_quality(self):
        for line in self:
            if line.lot_id:
                mo = self.env['mrp.production'].search([('lot_producing_id.name', '=', line.lot_id.name)], limit=1)
                line.weighted_average_quality = mo.weighted_average_pq if mo else 0.0
            else:
                line.weighted_average_quality = 0.0


    @api.depends('lot_id')
    def _compute_product_quantity(self):
        for line in self:
            if line.lot_id:
                mo = self.env['mrp.production'].search([('lot_producing_id.name', '=', line.lot_id.name)], limit=1)
                line.product_quantity = mo.product_qty if mo else 0.0
                line.average_product_quality = mo.weighted_average_pq if mo else 0.0
                line.product_cost = mo.purchase_cost if mo else 0.0
            else:
                line.product_quantity = 0.0
                line.average_product_quality = 0.0
                line.product_cost = 0.0
