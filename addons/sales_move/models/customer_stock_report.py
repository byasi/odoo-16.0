from odoo import api, fields, models

class CustomerStockReport(models.Model):
    _name = 'customer.stock.report'
    _description = 'Customer Stock Movement Report'
    _order = 'date desc'

    partner_id = fields.Many2one('res.partner', string='Customer', required=True)
    date = fields.Date(string='Date', required=True)
    move_id = fields.Many2one('account.move', string='Invoice')
    stock_move_id = fields.Many2one('stock.move', string='Stock Move')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    debit_qty = fields.Float(string='Debit Quantity', digits='Product Unit of Measure', default=0.0)
    credit_qty = fields.Float(string='Credit Quantity', digits='Product Unit of Measure', default=0.0)
    balance_qty = fields.Float(string='Balance Quantity', digits='Product Unit of Measure', compute='_compute_balance')
    opening_stock = fields.Float(string='Opening Stock', digits='Product Unit of Measure')
    move_type = fields.Selection([
        ('opening', 'Opening Balance'),
        ('sale', 'Sale'),
        ('purchase', 'Purchase'),
        ('return', 'Return'),
        ('adjustment', 'Adjustment')
    ], string='Movement Type', required=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, 
        default=lambda self: self.env.company)
    
    @api.depends('debit_qty', 'credit_qty', 'opening_stock')
    def _compute_balance(self):
        for record in self:
            record.balance_qty = record.opening_stock + record.credit_qty - record.debit_qty 