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

    @api.model
    def _get_outstanding_info_JSON(self):
        # Get the sales order from the invoice
        sales_order = self.env['sale.order'].search([('name', '=', self.invoice_origin)], limit=1)
        if not sales_order:
            return super()._get_outstanding_info_JSON()  # fallback to default

        outstanding_credits = []
        for payment in sales_order.selected_payment_ids:
            # Only include payments that are linked to this sales order
            if (
                payment.state in ('posted', 'reconciled')
                and payment.amount_residual > 0
                and payment.sales_order_id and payment.sales_order_id.id == sales_order.id
            ):
                outstanding_credits.append({
                    'journal_name': payment.journal_id.name,
                    'amount': payment.amount_residual,
                    'currency': payment.currency_id.name,
                    'payment_id': payment.id,
                    'payment_date': payment.payment_date,
                    'ref': payment.ref,
                })

        if not outstanding_credits:
            # No payments for this sales order, fallback to default
            return super()._get_outstanding_info_JSON()

        # Only show these payments, do not merge with others
        return {
            'title': 'Outstanding credits',
            'outstanding': True,
            'content': outstanding_credits,
        }

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