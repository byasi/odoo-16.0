from odoo import models, fields, api

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    weighted_average_pq = fields.Float(string="Weighted Average Product Quality")
    actual_weighted_pq = fields.Float(string="Actual Weighted Product Quality")
    product_quality = fields.Float(string="Product Quality")
    first_process_wt = fields.Float(string="First Process Wt")
    display_quantity = fields.Float(
        string="Display Quantity",
        # compute='_compute_display_quantity',
        store=True,
        readonly=True
    )

    # @api.depends('move_raw_ids')
    # def _compute_display_quantity(self):
    #     for production in self:
    #         disp = 10.0
    #         for move in production.move_raw_ids:
    #             disp = move.product_id.display_quantity