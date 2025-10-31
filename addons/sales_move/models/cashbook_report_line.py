from odoo import models, fields


class CashbookReportLine(models.TransientModel):
    _name = 'sales.move.cashbook.report.line'
    _description = 'Cashbook Report Line'

    date = fields.Date('Date', required=True)
    reference = fields.Char('Reference')
    description = fields.Char('Description')
    partner_id = fields.Many2one('res.partner', string='Partner')
    journal_id = fields.Many2one('account.journal', string='Journal')
    amount = fields.Float('Amount', digits=(16, 2))
    balance = fields.Float('Running Balance', digits=(16, 2))
    wizard_id = fields.Many2one('sales.move.cashbook.report.wizard', string='Wizard', required=True, ondelete='cascade')

