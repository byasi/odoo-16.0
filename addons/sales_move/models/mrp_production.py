from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    weighted_average_pq = fields.Float(string="Weighted Average Product Quality")
    actual_weighted_pq = fields.Float(string="Actual Weighted Product Quality")

