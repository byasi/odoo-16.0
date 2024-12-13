from odoo import api, fields, models, _
from odoo.tools import float_is_zero, float_compare, float_round

class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    product_uom_qty = fields.Float(
        string="Quantity",
        compute='_compute_product_uom_qty',
        digits='Product Unit of Measure', default=1.0,
        store=True, readonly=False, required=True, precompute=True)

    @api.depends('display_type', 'product_id', 'product_packaging_qty', 'qty_delivered')
    def _compute_product_uom_qty(self):
        for line in self:
            if line.display_type:
                line.product_uom_qty = 0.0
                continue

            if line.qty_delivered > 0:
                line.product_uom_qty = line.qty_delivered
                continue

            if not line.product_packaging_id:
                continue

            packaging_uom = line.product_packaging_id.product_uom_id
            qty_per_packaging = line.product_packaging_id.qty
            product_uom_qty = packaging_uom._compute_quantity(
                line.product_packaging_qty * qty_per_packaging, line.product_uom)

            if float_compare(product_uom_qty, line.product_uom_qty, precision_rounding=line.product_uom.rounding) != 0:
                line.product_uom_qty = product_uom_qty
