from odoo import models, fields, api
from datetime import date

class GeneralReportWizard(models.TransientModel):
    _name = 'sales.move.general.report.wizard'
    _description = 'General Report Wizard for Inventory and Sales Ledger'

    date_from = fields.Date('Date From', default=date.today().replace(day=1))
    date_to = fields.Date('Date To', default=date.today())
    product_id = fields.Many2one('product.product', string='Product', required=True)
    line_ids = fields.One2many('sales.move.general.report.line', 'wizard_id', string='Report Lines')

    def action_generate_report(self):
        self.line_ids.unlink()
        Product = self.env['product.product']
        MrpProduction = self.env['mrp.production']
        AccountMove = self.env['account.move']
        AccountMoveLine = self.env['account.move.line']
        if not self.product_id:
            return
        product = self.product_id
        # 1. Get all completed MOs for this product in date range (production events)
        mo_domain = [
            ('product_id', '=', product.id),
            ('state', '=', 'done'),
            ('date_finished', '>=', self.date_from),
            ('date_finished', '<=', self.date_to)
        ]
        mos = MrpProduction.search(mo_domain, order='date_finished asc')
        # 2. Get all sales (invoices) for this product in date range
        aml_domain = [
            ('product_id', '=', product.id),
            ('move_id.move_type', '=', 'out_invoice'),
            ('move_id.state', '=', 'posted'),
            ('move_id.invoice_date', '>=', self.date_from),
            ('move_id.invoice_date', '<=', self.date_to)
        ]
        amls = AccountMoveLine.search(aml_domain, order='date asc')
        # 3. Merge events (production and sales) by date
        events = []
        for mo in mos:
            events.append({
                'type': 'production',
                'date': mo.date_finished.date() if mo.date_finished else None,
                'doc_no': mo.name,
                'narration': mo.origin or 'Manufacturing',
                'qty': mo.product_qty,
                'amount': 0.0,
            })
        for aml in amls:
            events.append({
                'type': 'sale',
                'date': aml.move_id.invoice_date,
                'doc_no': aml.move_id.name,
                'narration': aml.move_id.invoice_origin or 'Sale',
                'qty': -aml.quantity,  # Sold quantity is negative for running balance
                'amount': aml.price_subtotal or 0.0,
            })
        # Sort all events by date
        events.sort(key=lambda e: (e['date'] or date.min, e['type']))
        running_qty = 0.0
        running_amount = 0.0
        for event in events:
            if event['type'] == 'production':
                running_qty += event['qty']
                self.env['sales.move.general.report.line'].create({
                    'wizard_id': self.id,
                    'doc_no': event['doc_no'],
                    'doc_date': event['date'],
                    'narration': event['narration'],
                    'xau_debit': event['qty'],
                    'xau_credit': 0.0,
                    'xau_balance': running_qty,
                    'amount_debit': 0.0,
                    'amount_credit': 0.0,
                    'amount_balance': running_amount,
                })
            elif event['type'] == 'sale':
                running_qty += event['qty']
                running_amount += event['amount']
                self.env['sales.move.general.report.line'].create({
                    'wizard_id': self.id,
                    'doc_no': event['doc_no'],
                    'doc_date': event['date'],
                    'narration': event['narration'],
                    'xau_debit': 0.0,
                    'xau_credit': -event['qty'],  # Show as positive in credit
                    'xau_balance': running_qty,
                    'amount_debit': 0.0,
                    'amount_credit': event['amount'],
                    'amount_balance': running_amount,
                })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sales.move.general.report.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        } 