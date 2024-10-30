from odoo import models, fields, api

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    weighted_average_pq = fields.Float(string="Weighted Average Product Quality", compute='_compute_weighted_average_pq',)
    actual_weighted_pq = fields.Float(string="Actual Weighted Product Quality")
    product_quality = fields.Float(string="Product Quality")
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
            # If we consider the `move_raw_ids` field (moves that bring in raw materials)
            # or `move_finished_ids` (moves that transfer finished goods)
            if production.move_raw_ids:
                # Retrieve the first related `stock.move` record's `display_quantity`
                # Customize as needed if there are multiple moves or a specific condition
                stock_move = production.move_raw_ids.filtered(lambda m: m.display_quantity).sorted('date', reverse=True)[:1]
                production.display_quantity = stock_move.display_quantity if stock_move else 0.0

    @api.depends('move_raw_ids.total_weighted_average')
    def _compute_weighted_average_pq(self):
        for production in self:
            # If we consider the `move_raw_ids` field (moves that bring in raw materials)
            # or `move_finished_ids` (moves that transfer finished goods)
            if production.move_raw_ids:
                stock_move = production.move_raw_ids.filtered(lambda m: m.total_weighted_average).sorted('date', reverse=True)[:1]
                production.weighted_average_pq = stock_move.total_weighted_average if stock_move else 0.0

class ChangeProductionQty(models.TransientModel):
    _inherit = 'change.production.qty'

    product_qty = fields.Float(
            'Quantity To Produce',
            compute='_compute_product_qty',
            digits='Product Unit of Measure', required=True)

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
                record.product_qty = 10.0