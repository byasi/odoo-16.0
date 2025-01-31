from odoo import  models, fields, api, _

class AccountMove(models.Model):
    _inherit = "account.move"
    invoice_date = fields.Date(
        string="Invoice/Bill Date",
        readonly=True,
        states={'draft': [('readonly', False)]},
        index=True,
        copy=False,
        default=fields.Date.context_today)

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
        When the currency is changed, convert the amount between currencies.
        Handles conversion both from USD to other currencies and vice versa.
        """
        if not (self.currency_id and self.amount and self.sales_order_id):
            return

        base_currency = self.env.ref('base.USD')

        # If no previous currency (new record), use base currency
        from_currency = self._origin.currency_id or base_currency
        to_currency = self.currency_id

        if from_currency == to_currency:
            return

        # First convert to USD if coming from another currency
        if from_currency != base_currency:
            amount_in_usd = from_currency._convert(
                self.amount,
                base_currency,
                self.env.user.company_id,
                fields.Date.context_today(self)
            )
        else:
            amount_in_usd = self.amount
        # Then convert from USD to target currency if needed
        if to_currency != base_currency:
            self.amount = base_currency._convert(
                amount_in_usd,
                to_currency,
                self.env.user.company_id,
                fields.Date.context_today(self)
            )
        else:
            self.amount = amount_in_usd

class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'
    currency = fields.Many2one('res.currency', string="Currency", default=lambda self: self.env.ref('base.USD').id)
    currency_rate = fields.Float(
        string="Currency Rate",
        compute='_compute_currency_rate',
        store=True,
        readonly=False
    )

    @api.depends('currency')
    def _compute_currency_rate(self):
        for record in self:
            record.currency_rate = record.currency.rate if record.currency else 1.0

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


class ResPartner(models.Model):
    _inherit = 'res.partner'

    property_account_receivable_id = fields.Many2one(
        'account.account',
        string="Account Receivable",
        default=lambda self: self.env['account.account'].search([('code', '=', '121000')], limit=1),
    )

    property_account_payable_id = fields.Many2one(
        'account.account',
        string="Account Payable",
        default=lambda self: self.env['account.account'].search([('code', '=', '211000')], limit=1),
    )
