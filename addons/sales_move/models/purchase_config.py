from odoo import models, fields, api

class PurchaseConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    method_1 = fields.Char(string="Method One", config_parameter='purchase_move.method_1')
    method_2 = fields.Char(string="Method Two", config_parameter='purchase_move.method_2')
    method_3 = fields.Char(string="Method Three", config_parameter='purchase_move.method_3')

    def set_values(self):
        super(PurchaseConfigSettings, self).set_values()
        # This will save the values to the config parameters
        self.env['ir.config_parameter'].sudo().set_param('purchase_move.method_1', self.method_1)
        self.env['ir.config_parameter'].sudo().set_param('purchase_move.method_2', self.method_2)
        self.env['ir.config_parameter'].sudo().set_param('purchase_move.method_3', self.method_3)
