
from odoo import  models, fields, api, _
class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def open_currency(self):
        return {
            'name': 'Currency',
            'type': 'ir.actions.act_window',
            'res_model': 'res.currency',
            'view_mode': 'tree,form',
            'target': 'current',
        }