from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

class PickingType(models.Model):
    _inherit = 'stock.picking.type'
