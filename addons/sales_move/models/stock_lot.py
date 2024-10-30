from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import math

class StockLot(models.Model):
    _inherit = "stock.lot"

    product_quality = fields.Float(
        string="Product 1 Quality",
        compute="_compute_product_quality",
        store=True
    )
    first_process_wt = fields.Float(
        string="First 1 Process Weight",
        compute="_compute_first_process_wt",
        store=True
    )

    @api.depends('product_quality')
    def _compute_product_quality(self):
        for lot in self:
            lot.product_quality = 20.0
            # Get the latest stock.move.line related to the lot
            # move_line = self.env['stock.move.line'].search(
            #     [('lot_id', '=', lot.id)],
            #     limit=1, order='date desc'
            # )
            # lot.product_quality = move_line.lot_product_quality if move_line else 10.0

    @api.depends('product_quality')
    def _compute_first_process_wt(self):
            for lot in self:
                lot.first_process_wt = 20.0
                # Get the latest stock.move.line related to the lot
                # move_line = self.env['stock.move.line'].search(
                #     [('lot_id', '=', lot.id)],
                #     limit=1, order='date desc'
                # )
                # lot.first_process_wt = move_line.lot_first_process_wt if move_line else 10.0

    # product_quality = fields.Float(string="Product Quality", compute="_compute_product_quality")
    # first_process_wt = fields.Float(string="First Process Wt", compute="_compute_first_process_wt")

    @api.depends('quant_ids.product_quality', 'quant_ids.location_id.usage')
    def _compute_product_quality(self):
        for lot in self:
            lot.product_quality = sum(
                quant.product_quality
                for quant in lot.quant_ids.filtered(lambda q: q.location_id.usage in ['internal', 'transit'])
            )

    @api.depends('quant_ids.first_process_wt', 'quant_ids.location_id.usage')
    def _compute_first_process_wt(self):
        for lot in self:
            lot.first_process_wt = sum(
                quant.first_process_wt
                for quant in lot.quant_ids.filtered(lambda q: q.location_id.usage in ['internal', 'transit'])
            )
