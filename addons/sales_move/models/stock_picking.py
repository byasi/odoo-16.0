from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    product_quality = fields.Float(string="Product Quality", compute="_compute_quality_and_weight", store=True)
    first_process_wt = fields.Float(string="First Process Wt", compute="_compute_quality_and_weight", store=True)
    weighted_average_quality = fields.Float(
        string="Product Quality",
        compute="_compute_weighted_average_quality",
        store=True
    )
    product_quantity = fields.Float(string="Product Quantity", compute="_compute_product_qty")

    @api.depends('move_ids_without_package.product_quality', 'move_ids_without_package.first_process_wt')
    def _compute_quality_and_weight(self):
        for picking in self:
            picking.product_quality = sum(picking.move_ids_without_package.mapped('product_quality'))
            picking.first_process_wt = sum(picking.move_ids_without_package.mapped('first_process_wt'))

    @api.depends('move_line_ids.lot_id')
    def _compute_weighted_average_quality(self):
        for picking in self:
            lot_number = picking.move_line_ids.filtered(lambda line: line.lot_id).mapped('lot_id.name')
            if lot_number:
                mo = self.env['mrp.production'].search([('lot_producing_id.name', '=', lot_number[0])], limit=1)
                picking.weighted_average_quality = mo.weighted_average_pq if mo else 0.0
            else:
                picking.weighted_average_quality = 0.0

    @api.depends('move_line_ids.lot_id')
    def _compute_product_qty(self):
        for picking in self:
            lot_number = picking.move_line_ids.filtered(lambda line: line.lot_id).mapped('lot_id.name')
            if lot_number:
                mo = self.env['mrp.production'].search([('lot_producing_id.name', '=', lot_number[0])], limit=1)
                picking.product_quantity = mo.product_qty if mo else 0.0
            else:
                picking.product_quantity = 0.0
