from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

class StockMove(models.Model):
    _inherit = 'stock.move'

    product_quality = fields.Float(string="Product Quality")
    first_process_wt = fields.Float(string="First Process Wt")
    display_quantity = fields.Float(
        string="Product Quantity",
        compute="_compute_display_quantity",
        store=True,
        readonly=True
    )

    @api.depends('move_line_ids', 'move_line_ids.lot_id', 'move_line_ids.lot_id.product_qty')
    def _compute_display_quantity(self):
        for move in self:
            lot_quantity = 0.0
            for line in move.move_line_ids:
                if line.lot_id:
                    lot_quantity = line.lot_id.product_qty
                    break  # Stop after finding the first lot_id
            move.display_quantity = lot_quantity

    @api.model_create_multi
    def _prepare_stock_moves(self, picking):
        res = super(StockMove, self)._prepare_stock_moves(picking)
        for move in res:
            move.update({
                'product_quality': self.product_quality,
                'first_process_wt': self.first_process_wt,
            })
        return res

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    product_quality = fields.Float(string="Product Quality", compute="_compute_quality_and_weight", store=True)
    first_process_wt = fields.Float(string="First Process Wt", compute="_compute_quality_and_weight", store=True)

    @api.depends('move_ids_without_package.product_quality', 'move_ids_without_package.first_process_wt')
    def _compute_quality_and_weight(self):
        for picking in self:
            picking.product_quality = sum(picking.move_ids_without_package.mapped('product_quality'))
            picking.first_process_wt = sum(picking.move_ids_without_package.mapped('first_process_wt'))

class StockQuant(models.Model):
    _inherit = "stock.quant"

    product_quality = fields.Float(string="Product Quality")
    first_process_wt = fields.Float(string="First Process Wt")

    @api.model
    def create(self, vals):
        quant = super(StockQuant, self).create(vals)
        if quant.product_id:
            # Search for the most recent stock move for this product and location
            move = self.env['stock.move'].search([
                ('product_id', '=', quant.product_id.id),
                ('location_dest_id', '=', quant.location_id.id),
                ('state', '=', 'done')
            ], order='date desc', limit=1)

            if move:
                _logger.info(f"Found move for quant {quant.id}:")
                _logger.info(f"Move ID: {move.id}")
                _logger.info(f"Product Quality: {move.product_quality}")
                _logger.info(f"First Process Wt: {move.first_process_wt}")
                quant.write({
                    'product_quality': move.product_quality,
                    'first_process_wt': move.first_process_wt,
                })
        return quant

class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    product_quality = fields.Float(string="Product Quality", related="move_id.product_quality", store=True)
    first_process_wt = fields.Float(string="First Process Wt", related="move_id.first_process_wt", store=True)


class StockLot(models.Model):
    _inherit = "stock.lot"

    product_quality = fields.Float(string="Product Quality", compute="_compute_product_quality")
    first_process_wt = fields.Float(string="First Process Wt", compute="_compute_first_process_wt")

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
