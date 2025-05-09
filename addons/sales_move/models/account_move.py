from odoo import models, api, _
from odoo.exceptions import UserError
from odoo.fields import Monetary

class AccountMove(models.Model):
    _inherit = 'account.move'

    total_unfixed_balance = Monetary(
        string="Total Unfixed Balance",
        compute='_compute_total_unfixed_balance',
        currency_field='currency_id',
        store=True
    )
    unfixed_balance_paid = Monetary(
        string="Unfixed Balance Paid",
        compute='_compute_unfixed_balance_paid',
        currency_field='currency_id',
        store=True
    )
    remaining_unfixed_balance = Monetary(
        string="Remaining Unfixed Balance",
        compute='_compute_remaining_unfixed_balance',
        currency_field='currency_id',
        store=True
    )

    @api.depends('invoice_line_ids.unfixed_balance')
    def _compute_total_unfixed_balance(self):
        for move in self:
            move.total_unfixed_balance = sum(move.invoice_line_ids.mapped('unfixed_balance'))

    @api.depends('line_ids.amount_currency', 'line_ids.debit', 'line_ids.credit', 'line_ids.currency_id', 'currency_id')
    def _compute_unfixed_balance_paid(self):
        for move in self:
            paid = 0.0
            for line in move.line_ids:
                # Only consider payment lines (liquidity or matched to a payment)
                if getattr(line.account_id, 'internal_type', False) == 'liquidity' or getattr(line, 'payment_id', False):
                    # Convert to invoice currency if needed
                    if line.currency_id and line.currency_id != move.currency_id:
                        paid += line.currency_id._convert(
                            abs(line.amount_currency),
                            move.currency_id,
                            move.company_id,
                            line.date or move.date or fields.Date.context_today(move)
                        )
                    else:
                        paid += abs(line.amount_currency)
            move.unfixed_balance_paid = paid

    @api.depends('total_unfixed_balance', 'unfixed_balance_paid')
    def _compute_remaining_unfixed_balance(self):
        for move in self:
            move.remaining_unfixed_balance = move.total_unfixed_balance - move.unfixed_balance_paid

    @api.depends('amount_residual', 'remaining_unfixed_balance', 'state')
    def _compute_payment_state(self):
        super()._compute_payment_state()
        for move in self:
            if move.state == 'posted' and move.total_unfixed_balance > 0:
                # If the remaining unfixed balance is now zero (with tolerance), mark as paid
                if abs(move.remaining_unfixed_balance) < 0.01:
                    move.payment_state = 'paid'
                elif move.remaining_unfixed_balance < move.total_unfixed_balance:
                    move.payment_state = 'partial'

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