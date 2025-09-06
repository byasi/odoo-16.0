from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import math

class StockLot(models.Model):
    _inherit = "stock.lot"

    product_quality = fields.Float(
        string="Product Quality",
        compute="_compute_product_quality",
        store=True
    )
    first_process_wt = fields.Float(
        string="First Process Weight",
        compute="_compute_first_process_wt",
        store=True
    )
    lot_original_subTotal = fields.Float(
        string="Lot Original Subtotal",
        compute="_compute_lot_original_subtotal",
        store=True
    )
    # NOTE these are values picked are not correct. wrong logic used
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

    @api.depends('quant_ids.lot_original_subTotal', 'quant_ids.location_id.usage')
    def _compute_lot_original_subtotal(self):
        for lot in self:
            lot.lot_original_subTotal = sum(
                quant.lot_original_subTotal
                for quant in lot.quant_ids.filtered(lambda q: q.location_id.usage in ['internal', 'transit'])
            )
