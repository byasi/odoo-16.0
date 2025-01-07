from odoo import api, fields, models

class SetUnfixedPriceWizard(models.Model):
    _name = 'sale.order.unfixedpricewizard'
    _description = "Fix Price"

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id.id
    )
    current_market_price = fields.Monetary(
        string="Current Market Price",
        currency_field='currency_id',
        required=True,
        store=True
    )
    _transient_cache = {}

    @api.model
    def default_get(self, fields_list):
        res = super(SetUnfixedPriceWizard, self).default_get(fields_list)
        # Load the last entered value from the transient cache
        last_value = self._transient_cache.get('current_market_price', 0.0)
        res['current_market_price'] = last_value
        return res

    def action_open_set_price_wizard(self):
        # Save the entered value to the transient cache
        self._transient_cache['current_market_price'] = self.current_market_price
        # Update the current_market_price in all Sale Orders
        sale_orders = self.env['sale.order'].search([])  # Fetch all sale orders
        sale_orders.write({'current_market_price': self.current_market_price})
        return True