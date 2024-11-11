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
    product_quality = fields.Float(string="Product Quality", store=True)
    first_process_wt = fields.Float(string="First Process Wt", store=True)
    lot_product_quality = fields.Float(string="Product Quality", related="move_id.product_quality", store=True)  # from Inventory
    lot_first_process_wt = fields.Float(string="First Process Wt", related="move_id.first_process_wt", store=True) # from Inventory
    mo_product_quality = fields.Float(string="Product Quality ", compute="_fetch_lot_values", store=True)  # from  manufacturing
    mo_first_process_wt = fields.Float(string="First Process Wt", compute="_fetch_lot_values", store=True) # from manufacturing

    # takes place in Manufacturing
    @api.depends('lot_id')
    def _fetch_lot_values(self):
        for line in self:
            if line.lot_id and line.lot_id.name:
                # Fetch the first record with the matching lot name
                matching_line = self.search([('lot_id.name', '=', line.lot_id.name)], limit=1)
                # Set the values
                line.mo_product_quality = matching_line.lot_product_quality
                line.mo_first_process_wt = matching_line.lot_first_process_wt
            else:
                line.mo_product_quality = 0.0
                line.mo_first_process_wt = 0.0

    qty_done = fields.Float(string="Done Quantity", compute="_compute_qty_done", store=True)

    @api.depends('move_id.product_uom_qty', 'lot_id', 'move_id.picking_type_id')
    def _compute_qty_done(self):
        for line in self:
            # if line.move_id.picking_type_id.code == 'mrp_operation':
            #     matching_line = self.search([('lot_id.name', '=', line.lot_id.name)], limit=1)
            #     line.qty_done = matching_line.lot_first_process_wt or 0.0
            if line.move_id.picking_type_id.code == 'outgoing':  # Specific to delivery orders
                line.qty_done = line.product_quantity or 0.0
            else:  # For inventory adjustments or other modules
                line.qty_done = line.move_id.product_uom_qty 

    @api.depends('lot_id')
    def _compute_weighted_average_quality(self):
        for line in self:
            if line.lot_id:
                # Search for the corresponding manufacturing order (MO) using the lot's name
                mo = self.env['mrp.production'].search([('lot_producing_id.name', '=', line.lot_id.name)], limit=1)
                # If found, set the weighted average product quality; otherwise, set to 0.0
                line.weighted_average_quality = mo.weighted_average_pq if mo else 0.0
            else:
                line.weighted_average_quality = 0.0

    product_quantity = fields.Float(string="Product Quantity", compute="_compute_product_qty", store=True)
    average_product_quality = fields.Float(string="Product Quality", compute="_compute_product_qty", store=True)


    @api.depends('lot_id')
    def _compute_product_qty(self):
      for line in self:
            if line.lot_id:
                # Search for the corresponding manufacturing order (MO) using the lot's name
                mo = self.env['mrp.production'].search([('lot_producing_id.name', '=', line.lot_id.name)], limit=1)
                # If found, set the weighted average product quality; otherwise, set to 0.0
                line.product_quantity = mo.display_quantity if mo else 0.0
                line.average_product_quality = mo.average_product_quality if mo else 0.0
            else:
                line.product_quantity = 0.0
                line.average_product_quality = 0.0