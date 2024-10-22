from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    formula_one = fields.Char(string="Formula One", config_parameter='sales_move.formula_one')
    formula_two = fields.Char(string="Formula Two", config_parameter='sales_move.formula_two')

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        # This will save the values to the config parameters
        self.env['ir.config_parameter'].sudo().set_param('sales_move.formula_one', self.formula_one)
        self.env['ir.config_parameter'].sudo().set_param('sales_move.formula_two', self.formula_two)
