from odoo import models, fields, api

class CustomerStockReport(models.Model):
    _name = 'customer.stock.report'
    _description = 'Customer Stock Report'
    
    name = fields.Char(string='Name')
    date = fields.Date(string='Date') 