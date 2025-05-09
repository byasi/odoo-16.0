from odoo import models, api, _
from odoo.exceptions import UserError

class AccountMove(models.Model):
    _inherit = 'account.move'

    def _create_stock_report_entry(self):
        CustomerStockReport = self.env['customer.stock.report']
        
        for move in self:
            if move.move_type not in ['out_invoice', 'out_refund', 'in_invoice', 'in_refund']:
                continue

            for line in move.invoice_line_ids.filtered(lambda l: l.product_id.type in ['product', 'consu']):
                move_type = 'sale'
                if move.move_type == 'out_refund':
                    move_type = 'return'
                elif move.move_type == 'in_invoice':
                    move_type = 'purchase'
                elif move.move_type == 'in_refund':
                    move_type = 'return'

                qty = line.quantity
                debit_qty = qty if move.move_type in ['out_invoice'] else 0
                credit_qty = qty if move.move_type in ['in_invoice', 'out_refund'] else 0

                # Get the related stock move if exists
                stock_move = self.env['stock.move'].search([
                    ('picking_id.origin', '=', move.invoice_origin),
                    ('product_id', '=', line.product_id.id)
                ], limit=1)

                CustomerStockReport.create({
                    'partner_id': move.partner_id.id,
                    'date': move.date,
                    'move_id': move.id,
                    'stock_move_id': stock_move.id if stock_move else False,
                    'product_id': line.product_id.id,
                    'debit_qty': debit_qty,
                    'credit_qty': credit_qty,
                    'move_type': move_type,
                    'opening_stock': 0.0,  # This will be handled by a separate wizard
                })

    def action_post(self):
        res = super().action_post()
        self._create_stock_report_entry()
        return res 