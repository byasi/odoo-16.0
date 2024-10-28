from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import math

class StockMove(models.Model):
    _inherit = 'stock.move'
    def custom_round_down(self, value):
        scaled_value = value * 100
        rounded_down_value = math.floor(scaled_value) / 100
        return rounded_down_value

    product_quality = fields.Float(string="Product Quality")
    first_process_wt = fields.Float(string="First Process Wt")
    mo_product_quality = fields.Float(string="MO Product Quality")
    mo_first_process_wt = fields.Float(string="MO First Process Wt")
    total_weighted_average = fields.Float(
    string="Total Weighted Average",
    compute="_compute_total_weighted_average",
    store=True,
    readonly=True
    )
    display_quantity = fields.Float(
    string="Product Quantity",
    compute="_compute_display_quantity",
    store=True,
    readonly=True)

    average_lot_product_quality = fields.Float(
        string="Average Lot Product Quality",
        compute="_compute_average_values",
        store=True,
        readonly=True
    )
    average_lot_first_process_wt = fields.Float(
        string="Average Lot First Process Wt",
        compute="_compute_average_values",
        store=True,
        readonly=True
    )
    @api.depends('move_line_ids.lot_product_quality', 'move_line_ids.lot_first_process_wt')
    def _compute_average_values(self):
        for move in self:
            total_lines = len(move.move_line_ids)
            total_product_quality = self.custom_round_down(sum(line.lot_product_quality for line in move.move_line_ids))
            total_first_process_wt = self.custom_round_down(sum(line.lot_first_process_wt for line in move.move_line_ids))

            move.average_lot_product_quality = self.custom_round_down((total_product_quality / total_lines)) if total_lines else 0.0
            move.average_lot_first_process_wt = self.custom_round_down((total_first_process_wt / total_lines)) if total_lines else 0.0

    @api.depends('move_line_ids.lot_product_quality', 'move_line_ids.lot_first_process_wt')
    def _compute_total_weighted_average(self):
        for move in self:
            total_quality = self.custom_round_down(sum(line.lot_product_quality for line in move.move_line_ids))
            total_weighted_value = self.custom_round_down(sum(line.lot_product_quality * line.lot_first_process_wt for line in move.move_line_ids))
            move.total_weighted_average = self.custom_round_down((total_weighted_value / total_quality) ) if total_quality else 0.0

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
                quant.write({
                    'product_quality': move.product_quality,
                    'first_process_wt': move.first_process_wt,
                })
        return quant

class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    product_quality = fields.Float(string="Product Quality", store=True)
    first_process_wt = fields.Float(string="First Process Wt", store=True)
    lot_product_quality = fields.Float(string="Lot Product Quality", compute="_fetch_lot_values", store=True)
    lot_first_process_wt = fields.Float(string="Lot First Process Wt", compute="_fetch_lot_values", store=True)

    total_weighted_average = fields.Float(
        string="Total Weighted Average",
        compute="_compute_total_weighted_average",
        store=True,
        readonly=True)

    @api.depends('lot_product_quality', 'lot_first_process_wt')
    def _compute_total_weighted_average(self):
        total_quality = sum(line.lot_product_quality for line in self)
        total_weighted_value = sum(line.lot_product_quality * line.lot_first_process_wt for line in self)
        for line in self:
            line.total_weighted_average = (total_weighted_value / total_quality) if total_quality else 0.0


    @api.depends('lot_id')
    def _fetch_lot_values(self):
        for line in self:
            if line.lot_id and line.lot_id.name:
                # Fetch the first record with the matching lot name
                matching_line = self.search([('lot_id.name', '=', line.lot_id.name)], limit=1)
                # Set the values
                line.lot_product_quality = matching_line.product_quality
                line.lot_first_process_wt = matching_line.first_process_wt
            else:
                line.lot_product_quality = 0.0
                line.lot_first_process_wt = 0.0

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

class ChangeProductionQty(models.TransientModel):
    _inherit = 'change.production.qty'

    # product_qty = fields.Float(
    #     string="Product Quantity",
    #     compute="_compute_product_qty_from_display_quantity",
    #     store=True,
    #     readonly=False
    # )

    # @api.depends('production_id')
    # def _compute_product_qty_from_display_quantity(self):
    #     for record in self:
    #         if record.production_id:
    #             # Find all Stock Moves linked to this production order
    #             stock_moves = self.env['stock.move'].search([('production_id', '=', record.production_id.id)])
    #             # Sum up the display_quantity of all related Stock Moves
    #             record.product_qty = sum(move.display_quantity for move in stock_moves)
