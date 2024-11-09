from odoo import models, fields, api

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    weighted_average_pq = fields.Float(string="Weighted Average Product Quality", compute='_compute_weighted_average_pq',)
    actual_weighted_pq = fields.Float(string="Actual Weighted Product Quality")
    average_product_quality = fields.Float(string="Product Quality", compute="_compute_product_quality")
    first_process_wt = fields.Float(string="First Process Wt")
    display_quantity = fields.Float(
        string="Display Quantity",
        compute='_compute_display_quantity',
        store=True,
        readonly=True
    )

    @api.depends('move_raw_ids.display_quantity')
    def _compute_display_quantity(self):
        for production in self:
            if production.move_raw_ids:
                stock_move = production.move_raw_ids.filtered(lambda m: m.display_quantity).sorted('date', reverse=True)[:1]
                production.display_quantity = stock_move.display_quantity if stock_move else 0.0
            else:
                production.display_quantity = 0.0

    @api.depends('move_raw_ids.average_lot_product_quality')
    def _compute_product_quality(self):
        for production in self:
            if production.move_raw_ids:
                stock_move = production.move_raw_ids.filtered(lambda m: m.average_lot_product_quality).sorted('date', reverse=True)[:1]
                production.average_product_quality = stock_move.average_lot_product_quality if stock_move else 0.0
            else:
                production.average_product_quality = 0.0


    @api.depends('move_raw_ids.total_weighted_average')
    def _compute_weighted_average_pq(self):
        for production in self:
            if production.move_raw_ids:
                stock_move = production.move_raw_ids.filtered(lambda m: m.total_weighted_average).sorted('date', reverse=True)[:1]
                production.weighted_average_pq = stock_move.total_weighted_average if stock_move else 0.0
            else:
                production.weighted_average_pq = 0.0

class ChangeProductionQty(models.TransientModel):
    _inherit = 'change.production.qty'

    product_qty = fields.Float(
            'Quantity To Produce',
            compute='_compute_product_qty',
            digits='Product Unit of Measure',store=True)

    # overrides the
    @api.depends_context('active_id')
    def _compute_product_qty(self):
        # Access the production order using the active_id from the context
        for record in self:
            production_id = self.env.context.get('active_id')
            if production_id:
                production = self.env['mrp.production'].browse(production_id)
                record.product_qty = production.display_quantity
            else:
                record.product_qty = 0.0