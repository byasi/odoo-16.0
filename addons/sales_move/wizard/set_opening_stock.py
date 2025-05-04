from odoo import api, fields, models

class SetOpeningStock(models.TransientModel):
    _name = 'set.opening.stock.wizard'
    _description = 'Set Opening Stock Wizard'

    partner_id = fields.Many2one('res.partner', string='Customer', required=True)
    date = fields.Date(string='Opening Date', required=True, default=fields.Date.context_today)
    line_ids = fields.One2many('set.opening.stock.line.wizard', 'wizard_id', string='Products')

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id:
            # Get all products that have been involved in transactions with this partner
            products = self.env['customer.stock.report'].search([
                ('partner_id', '=', self.partner_id.id)
            ]).mapped('product_id')
            
            self.line_ids = [(0, 0, {'product_id': product.id}) for product in products]

    def action_set_opening_stock(self):
        CustomerStockReport = self.env['customer.stock.report']
        for line in self.line_ids:
            if line.opening_stock != 0:
                CustomerStockReport.create({
                    'partner_id': self.partner_id.id,
                    'date': self.date,
                    'product_id': line.product_id.id,
                    'opening_stock': line.opening_stock,
                    'move_type': 'opening',
                })
        return {'type': 'ir.actions.act_window_close'}

class SetOpeningStockLine(models.TransientModel):
    _name = 'set.opening.stock.line.wizard'
    _description = 'Set Opening Stock Line Wizard'

    wizard_id = fields.Many2one('set.opening.stock.wizard', string='Wizard')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    opening_stock = fields.Float(string='Opening Stock', digits='Product Unit of Measure', default=0.0) 