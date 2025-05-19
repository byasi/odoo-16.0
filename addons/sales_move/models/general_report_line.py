from odoo import models, fields

class GeneralReportLine(models.TransientModel):
    _name = 'sales.move.general.report.line'
    _description = 'General Report Line for Inventory and Sales Ledger'

    doc_no = fields.Char('Doc No')
    doc_date = fields.Date('Doc Date')
    narration = fields.Char('Narration')

    amount_debit = fields.Float('Amount (USD) Debit')
    amount_credit = fields.Float('Amount (USD) Credit')
    amount_balance = fields.Float('Amount (USD) Balance')

    xau_debit = fields.Float('XAU(GMS) Debit')
    xau_credit = fields.Float('XAU(GMS) Credit')
    xau_balance = fields.Float('XAU(GMS) Balance')

    wizard_id = fields.Many2one('sales.move.general.report.wizard', string='Wizard') 