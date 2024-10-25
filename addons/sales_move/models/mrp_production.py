from odoo import models, fields, api

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    weighted_average_pq = fields.Float(string="Weighted Average Product Quality")
    actual_weighted_pq = fields.Float(string="Actual Weighted Product Quality")
    product_quality = fields.Float(string="Product Quality")
    first_process_wt = fields.Float(string="First Process Wt")

    def update_quality_from_moves(self):
        """ Update product_quality and first_process_wt from related stock moves """
        for production in self:
            # Assuming stock moves are linked to mrp.production through a related field
            stock_moves = self.env['stock.move'].search([('production_id', '=', production.id)])

            if stock_moves:
                # Aggregate or select the values from the related stock moves
                production.product_quality = sum(move.product_quality for move in stock_moves)
                production.first_process_wt = sum(move.first_process_wt for move in stock_moves)
