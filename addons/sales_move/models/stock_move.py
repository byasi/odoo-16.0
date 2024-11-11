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
    actual_weighted_pq = fields.Float(string="Actual Weighted Product Quality")
    first_process_wt = fields.Float(string="First Process Wt")
    total_weighted_average = fields.Float(
    string="Total Weighted Average Quality",
    compute="_compute_total_weighted_average",
    store=True,
    readonly=True
    )
    display_quantity = fields.Float(
    string="Product Quantity",
    related="quantity_done",
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

    @api.depends('move_line_ids.mo_product_quality', 'move_line_ids.mo_first_process_wt')
    def _compute_average_values(self):
        for move in self:
            total_lines = len(move.move_line_ids)
            total_product_quality = self.custom_round_down(sum(line.mo_product_quality for line in move.move_line_ids))
            total_first_process_wt = self.custom_round_down(sum(line.mo_first_process_wt for line in move.move_line_ids))

            move.average_lot_product_quality = self.custom_round_down((total_product_quality / total_lines)) if total_lines else 0.0
            move.average_lot_first_process_wt = self.custom_round_down((total_first_process_wt / total_lines)) if total_lines else 0.0

    @api.depends('move_line_ids.mo_product_quality', 'move_line_ids.mo_first_process_wt', 'display_quantity')
    def _compute_total_weighted_average(self):
        for move in self:
            total_quantity =  move.display_quantity
            # total_quality = self.custom_round_down(sum(line.lot_product_quality for line in move.move_line_ids))
            # NOTE  divide by totalquantity not totalquality
            total_weighted_quality = self.custom_round_down(sum(self.custom_round_down(line.mo_product_quality * line.mo_first_process_wt) for line in move.move_line_ids))
            move.total_weighted_average = self.custom_round_down((total_weighted_quality / move.display_quantity) ) if total_quantity else 0.0


    @api.model_create_multi
    def _prepare_stock_moves(self, picking):
        res = super(StockMove, self)._prepare_stock_moves(picking)
        for move in res:
            move.update({
                'product_quality': self.product_quality,
                'first_process_wt': self.first_process_wt,
            })
        return res



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

