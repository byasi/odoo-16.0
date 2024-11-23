from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import math

class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    weighted_average_quality = fields.Float(
        string="Product Quality",
        compute="_compute_weighted_average_quality",
        store=True
    )
    # product_quality = fields.Float(string="Product Quality", store=True)
    # first_process_wt = fields.Float(string="First Process Wt", store=True)
    lot_product_quality = fields.Float(string="Product Quality", compute="_compute_lot_product_quality", store=True)  # from Inventory
    lot_first_process_wt = fields.Float(string="First Process Wt", compute="_compute_lot_first_process_wt", store=True) # from Inventory
    mo_product_quality = fields.Float(string="Product Quality ", compute="_fetch_lot_values", store=True)  # from  manufacturing
    mo_first_process_wt = fields.Float(string="First Process Wt", compute="_fetch_lot_values", store=True) # from manufacturing

    @api.depends('move_id.product_quality')
    def _compute_lot_product_quality(self):
        for line in self:
            line.lot_product_quality = line.move_id.product_quality

    @api.depends('move_id.first_process_wt')
    def _compute_lot_first_process_wt(self):
        for line in self:
            line.lot_first_process_wt = line.move_id.first_process_wt

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
                else:
                    # If no matching line is found, set to 0.0
                    line.mo_product_quality = 0.0
                    line.mo_first_process_wt = 0.0
            else:
                line.mo_product_quality = 0.0
                line.mo_first_process_wt = 0.0


    qty_done = fields.Float(string="Done Quantity", compute="_compute_qty_done", store=True)

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

    product_quantity = fields.Float(string="Product Quantity", compute="_compute_product_quantity", store=True)
    average_product_quality = fields.Float(string="Product Quality", compute="_compute_product_quantity", store=True)

    @api.depends('lot_id')
    def _compute_product_quantity(self):
        for line in self:
            if line.lot_id:
                mo = self.env['mrp.production'].search([('lot_producing_id.name', '=', line.lot_id.name)], limit=1)
                line.product_quantity = mo.product_qty if mo else 0.0
                line.average_product_quality = mo.weighted_average_pq if mo else 0.0
            else:
                line.product_quantity = 0.0
                line.average_product_quality = 0.0
