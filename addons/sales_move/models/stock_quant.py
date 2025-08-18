from odoo import models, fields, api

class StockQuant(models.Model):
    _inherit = 'stock.quant'

    product_quality = fields.Float(string="Product Quality")
    first_process_wt = fields.Float(string="First Process Wt")
    manual_first_process = fields.Float(string="Manual First Process Wt")
    manual_product_quality = fields.Float(string="Manual Product Quality")

    @api.model
    def create(self, vals):
        quant = super(StockQuant, self).create(vals)
        
        # If this quant is created from a stock move, copy the relevant fields
        if 'move_ids' in vals:
            move = self.env['stock.move'].browse(vals['move_ids'][0][2]) if vals['move_ids'] else False
            if move:
                vals.update({
                    'product_quality': move.product_quality,
                    'first_process_wt': move.first_process_wt,
                    'manual_first_process': move.manual_first_process,
                    'manual_product_quality': move.manual_product_quality,
                })
        
        return quant
