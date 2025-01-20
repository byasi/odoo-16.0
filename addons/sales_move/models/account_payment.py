
from odoo import  models, fields, api, _

class AccountPayment(models.Model):
    _inherit = "account.payment"
    currency = fields.Many2one('res.currency', string="Currency", default=lambda self: self.env.ref('base.USD').id)
    sales_order_id = fields.Many2one(
        'sale.order',
        string="Select Sales Order",
        domain="[('partner_id', '=', partner_id)]",  # Filter sales orders by customer
        help="Sales orders attached to the selected customer."
    )
    amount = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        compute='_compute_currency_id', store=True, readonly=False, precompute=True,
        help="The payment's currency.")

    @api.depends('journal_id')
    def _compute_currency_id(self):
        for pay in self:
            pay.currency_id = pay.journal_id.currency_id or pay.journal_id.company_id.currency_id

    @api.onchange('sales_order_id')
    def _onchange_sales_order_id(self):
        """
        When a sales order is selected, update the amount in the payment.
        """
        if self.sales_order_id:
            # base_currency = self.env.user
            self.amount = self.sales_order_id.unfixed_balance
        else:
            self.amount = 0.0

    @api.onchange('currency_id')
    def _onchange_currency_id(self):
        """
        When the currency is changed, convert the amount to the selected currency.
        """
        if self.currency_id and self.amount:
            original_currency = self.env.ref('base.USD')
            if self.currency_id != original_currency:
                # Convert from original currency to the selected currency
                self.amount = original_currency._convert(
                    self.amount,
                    self.currency_id,
                    self.env.user.company_id,
                    fields.Date.context_today(self)
                )
class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'
    currency = fields.Many2one('res.currency', string="Currency", default=lambda self: self.env.ref('base.USD').id)

    def open_currency(self):
        return {
            'name': 'Currency',
            'type': 'ir.actions.act_window',
            'res_model': 'res.currency',
            'view_mode': 'tree,form',
            'target': 'current',
        }

class CurrencyRate(models.Model):
    _inherit = "res.currency.rate"

    name = fields.Datetime(string='Date', required=True, index=True,
        default=fields.Datetime.now)
