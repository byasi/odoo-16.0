from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_is_zero, float_compare, float_round
import math

class SetUnfixedPriceWizard(models.TransientModel):
    _name = 'sale.order.unfixedpricewizard'
    _description = "Fix Price"
    currency_id = fields.Many2one('res.currency', 'Currency', required=True, 
        default=lambda self: self.env.company.currency_id.id)
    current_market_price = fields.Monetary(string="Current Market Price",currency_field='currency_id', required=True)

    def action_open_set_price_wizard(self):
        pass
        # return {
        #     'name': 'Set Current Market Price',
        #     'type': 'ir.actions.act_window',
        #     'res_model': 'set.current.market.price.wizard',
        #     'view_mode': 'form',
        #     'target': 'new',
        # }