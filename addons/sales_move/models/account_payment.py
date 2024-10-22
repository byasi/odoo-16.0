from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

class AccountMove(models.Model):
    _inherit = "account.move"

    @api.model
    def _get_formula_selection(self):
        ICPSudo = self.env['ir.config_parameter'].sudo()
        formula_one = ICPSudo.get_param('sales_move.formula_one', default='selling_price - buying_price')
        formula_two = ICPSudo.get_param('sales_move.formula_two', default='selling_price + buying_price')
        return [
            ('formula1', formula_one),
            ('formula2', formula_two),
        ]

    calc_field = fields.Selection(
        selection=_get_formula_selection,
        string="Formula"
    )
    calc_result = fields.Float(string="Result", readonly=True)
    selling_price = fields.Float(string="Selling Price")
    buying_price = fields.Float(string="Buying Price")
    profit = fields.Float(string="Profit", readonly=True)

    def calculate(self):
        for record in self:
            try:
                local_variables = {
                    'selling_price': record.selling_price,
                    'buying_price': record.buying_price,
                    'profit': record.profit,
                }
                formula = dict(self._get_formula_selection())[record.calc_field]
                result = eval(formula, {"__builtins__": None}, local_variables)
                record.calc_result = result
            except Exception as e:
                record.calc_result = 0.0
                raise UserError(f"Error in calculation: {e}")

class SalesMove(models.Model):
    _inherit = 'sale.order'