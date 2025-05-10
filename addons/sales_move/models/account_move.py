from odoo import models, fields, api
from datetime import date

class AccountMove(models.Model):
    _inherit = 'account.move'

    is_invoice_date_past = fields.Boolean(
        compute="_compute_is_invoice_date_past", store=True
    )
    is_date_past = fields.Boolean(
        compute="_compute_is_date_past", store=True
    )
    manual_quantity_so = fields.Float(string="Manual Quantity SO")
    price_currency = fields.Monetary(string="Price Currency", currency_field='currency_id')
    total_unfixed_balance = fields.Monetary(
        string='Total Unfixed Balance',
        compute='_compute_total_unfixed_balance',
        store=True,
        currency_field='currency_id'
    )

    @api.depends('invoice_line_ids.unfixed_balance')
    def _compute_total_unfixed_balance(self):
        for move in self:
            move.total_unfixed_balance = sum(move.invoice_line_ids.mapped('unfixed_balance'))

    @api.depends('invoice_date')
    def _compute_is_invoice_date_past(self):
        for order in self:
            order.is_invoice_date_past = order.invoice_date and order.invoice_date < date.today()

    @api.depends('date')
    def _compute_is_date_past(self):
        for order in self:
            order.is_date_past = order.date and order.date < date.today()

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    unfixed_balance = fields.Monetary(
        string='Unfixed Balance',
        compute='_compute_unfixed_balance',
        store=True,
        currency_field='currency_id'
    )

    @api.depends('price_subtotal', 'move_id.payment_id.amount')
    def _compute_unfixed_balance(self):
        for line in self:
            if line.move_id.move_type == 'out_invoice':
                # Get the total payments for this invoice
                total_payments = sum(line.move_id.payment_id.mapped('amount'))
                # Calculate unfixed balance as the difference between subtotal and payments
                line.unfixed_balance = line.price_subtotal - total_payments
            else:
                line.unfixed_balance = 0.0 