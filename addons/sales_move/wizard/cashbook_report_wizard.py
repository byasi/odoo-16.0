from odoo import models, fields, api, _
from datetime import date, datetime
import base64
import io

# TODO: Add foreign currency


class CashbookReportWizard(models.TransientModel):
    _name = 'sales.move.cashbook.report.wizard'
    _description = 'Cashbook Report Wizard'

    target_move = fields.Selection([
        ('posted', 'All Posted Entries'),
        ('all', 'All Entries')
    ], string='Target Moves', required=True, default='posted')
    
    date_from = fields.Date('Start Date', default=date.today(), required=True)
    date_to = fields.Date('End Date', default=date.today(), required=True)
    
    initial_balance = fields.Boolean('Include Initial Balances', default=True,
                                       help='If checked, the opening balance will be included in the report. If not, the report will start from the selected date range.')
    
    sort_selection = fields.Selection([
        ('date', 'Date'),
        ('journal_and_partner', 'Journal & Partner')
    ], string='Sort by', required=True, default='date')
    
    currency_id = fields.Many2one('res.currency', string='Currency', 
                                  default=lambda self: self.env.company.currency_id,
                                  required=True,
                                  help='Select the currency to display amounts in the report')
    
    account_ids = fields.Many2many('account.account', 'cashbook_account_rel', 'wizard_id', 'account_id',
                                     string='Accounts', required=True,
                                     default=lambda self: self.env['account.account'].search([('code', '=', '173')], limit=1) if self.env['account.account'].search([('code', '=', '173')], limit=1) else False,
                                     domain="[('deprecated', '=', False)]")
    
    journal_ids = fields.Many2many('account.journal', 'cashbook_journal_rel', 'wizard_id', 'journal_id',
                                     string='Journals',
                                     domain=[])

    opening_balance = fields.Float('Opening Balance', readonly=True, compute='_compute_opening_balance')
    line_ids = fields.One2many('sales.move.cashbook.report.line', 'wizard_id', string='Report Lines')
    
    @api.depends('currency_id')
    def _get_currency(self):
        """Get currency for report templates"""
        return self.currency_id or self.env.company.currency_id

    @api.depends('account_ids', 'date_from', 'initial_balance', 'target_move', 'currency_id')
    def _compute_opening_balance(self):
        """Compute opening balance from the account before the start date"""
        for wizard in self:
            if not wizard.account_ids or not wizard.date_from or not wizard.currency_id:
                wizard.opening_balance = 0.0
                continue
            
            if not wizard.initial_balance:
                wizard.opening_balance = 0.0
                continue
            
            account_ids = wizard.account_ids.ids
            company = self.env.company
            
            # Calculate opening balance by summing all amount_currency before start date
            # Using amount_currency to match the report lines calculation
            # When amount_currency is NULL (company currency lines), use balance instead
            query = """
                SELECT 
                    aml.account_id,
                    COALESCE(SUM(COALESCE(aml.amount_currency, aml.balance)), 0.0) as balance,
                    aml.currency_id,
                    aml.company_id
                FROM account_move_line aml
                WHERE aml.account_id IN %s
                AND aml.date < %s
            """
            # Add state filter if only posted moves
            if wizard.target_move == 'posted':
                query += """
                    AND aml.move_id IN (
                        SELECT id FROM account_move WHERE state = 'posted'
                    )
                """
            
            query += """
                GROUP BY aml.account_id, aml.currency_id, aml.company_id
            """
            
            self.env.cr.execute(query, (tuple(account_ids), wizard.date_from))
            results = self.env.cr.dictfetchall()
            
            total_balance = 0.0
            company_currency = company.currency_id
            
            for row in results:
                balance = row['balance']
                
                # If the line has a different currency, convert it
                if row['currency_id']:
                    line_currency = self.env['res.currency'].browse(row['currency_id'])
                    if line_currency != company_currency:
                        # Convert from line currency to company currency
                        balance = line_currency._convert(
                            balance,
                            company_currency,
                            company,
                            wizard.date_from
                        )
                
                total_balance -= balance
            
            # Convert to selected currency
            if wizard.currency_id != company_currency and total_balance != 0:
                total_balance = company_currency._convert(
                    total_balance,
                    wizard.currency_id,
                    company,
                    wizard.date_from
                )
            
            wizard.opening_balance = total_balance

    def action_generate_report(self):
        """Generate the cashbook report"""
        self.line_ids.unlink()
        
        if not self.account_ids:
            return
        
        # Build domain for query
        domain = [
            ('account_id', 'in', self.account_ids.ids),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to)
        ]
        
        # Add state filter if only posted moves
        if self.target_move == 'posted':
            domain.append(('move_id.state', '=', 'posted'))
        
        # Add journal filter if provided
        if self.journal_ids:
            domain.append(('move_id.journal_id', 'in', self.journal_ids.ids))
        
        # Determine sort order
        order_by = 'date, id'
        if self.sort_selection == 'journal_and_partner':
            order_by = 'journal_id, partner_id, date, id'

        # Search for move lines
        move_lines = self.env['account.move.line'].search(domain, order=order_by)

        # Initialize running balance
        running_balance = self.opening_balance
        company_currency = self.env.company.currency_id

        # Process each move line
        for line in move_lines:
            # Get the currency for this line
            line_currency = line.currency_id or company_currency
            # Use amount_currency directly when available (as requested)
            # If not available, fall back to balance.
            # Make amount negative so it deducts when added to running balance
            amount = (line.amount_currency if line.amount_currency else line.balance)

            # Update running balance by adding (amount is already negative)
            running_balance -= amount

            # Get description (from move or line)
            description = line.name or line.move_id.ref or line.move_id.name or ''

            # Create report line
            self.env['sales.move.cashbook.report.line'].create({
                'wizard_id': self.id,
                'date': line.date,
                'reference': line.move_id.name or line.move_id.ref or '',
                'description': description,
                'partner_id': line.partner_id.id,
                'journal_id': line.journal_id.id,
                'amount': amount,
                'balance': running_balance,
            })
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sales.move.cashbook.report.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    def action_print_pdf(self):
        """Print PDF report"""
        return self.env.ref('sales_move.action_cashbook_report_pdf').report_action(self)

    def action_export_excel(self):
        """Export cashbook report to Excel"""
        try:
            import xlsxwriter
        except ImportError:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Warning'),
                    'message': _('Please install xlsxwriter: pip install xlsxwriter'),
                    'type': 'danger',
                    'sticky': False,
                }
            }

        # Create output stream
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Cashbook Report')

        # Define formats
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#366092',
            'font_color': '#FFFFFF',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1
        })
        title_format = workbook.add_format({
            'bold': True,
            'font_size': 14,
        })
        label_format = workbook.add_format({
            'bold': True,
        })
        currency_format = workbook.add_format({
            'num_format': '#,##0.00',
            'align': 'right',
        })
        date_format = workbook.add_format({
            'num_format': 'dd/mm/yyyy',
            'align': 'center',
        })
        border_format = workbook.add_format({
            'border': 1,
        })

        # Write report header
        row = 0
        worksheet.write(row, 0, 'Cash Book Report', title_format)
        row += 1
        
        # Write report details
        if self.account_ids:
            worksheet.write(row, 0, 'Accounts:', label_format)
            account_names = ', '.join([f"{acc.code} - {acc.name}" for acc in self.account_ids[:3]])
            if len(self.account_ids) > 3:
                account_names += f" (+{len(self.account_ids) - 3} more)"
            worksheet.write(row, 1, account_names)
            row += 1
        
        worksheet.write(row, 0, 'Target Moves:', label_format)
        worksheet.write(row, 1, 'All Posted Entries' if self.target_move == 'posted' else 'All Entries')
        row += 1
        
        worksheet.write(row, 0, 'Start Date:', label_format)
        worksheet.write(row, 1, self.date_from.strftime('%d/%m/%Y'))
        row += 1
        
        worksheet.write(row, 0, 'End Date:', label_format)
        worksheet.write(row, 1, self.date_to.strftime('%d/%m/%Y'))
        row += 1
        
        worksheet.write(row, 0, 'Currency:', label_format)
        worksheet.write(row, 1, self.currency_id.name)
        row += 1
        
        worksheet.write(row, 0, 'Opening Balance:', label_format)
        worksheet.write(row, 1, self.opening_balance, currency_format)
        row += 1
        
        if self.journal_ids:
            worksheet.write(row, 0, 'Journals:', label_format)
            journal_names = ', '.join([j.name for j in self.journal_ids[:5]])
            if len(self.journal_ids) > 5:
                journal_names += f" (+{len(self.journal_ids) - 5} more)"
            worksheet.write(row, 1, journal_names)
            row += 1
        
        row += 1

        # Write column headers
        headers = ['Date', 'Reference', 'Description', 'Amount', 'Balance']
        # Add optional columns if sorting by journal
        if self.sort_selection == 'journal_and_partner':
            headers.insert(2, 'Journal')
            headers.insert(3, 'Partner')
        
        for col, header in enumerate(headers):
            worksheet.write(row, col, header, header_format)
            worksheet.set_column(col, col, 15)  # Set column width
        
        row += 1

        # Write opening balance row
        col_offset = 2 if self.sort_selection == 'journal_and_partner' else 0
        worksheet.write(row, 0, 'Opening Balance', border_format)
        worksheet.write(row, 1 + col_offset, '', border_format)
        worksheet.write(row, 2 + col_offset, 'Opening Balance', border_format)
        worksheet.write(row, 3 + col_offset, 0, currency_format)
        worksheet.write(row, 4 + col_offset, self.opening_balance, currency_format)
        row += 1

        # Write transaction lines
        for line in self.line_ids:
            col = 0
            worksheet.write(row, col, line.date, date_format)
            col += 1
            worksheet.write(row, col, line.reference or '', border_format)
            col += 1
            
            # Add journal and partner if sorting by journal
            if self.sort_selection == 'journal_and_partner':
                worksheet.write(row, col, line.journal_id.name if line.journal_id else '', border_format)
                col += 1
                worksheet.write(row, col, line.partner_id.name if line.partner_id else '', border_format)
                col += 1
            
            worksheet.write(row, col, line.description or '', border_format)
            col += 1
            worksheet.write(row, col, line.amount, currency_format)
            col += 1
            worksheet.write(row, col, line.balance, currency_format)
            row += 1

        # Close workbook
        workbook.close()
        output.seek(0)

        # Create attachment
        account_codes = ', '.join([acc.code for acc in self.account_ids[:3]]) if self.account_ids else 'Unknown'
        filename = f"Cashbook_Report_{account_codes}_{self.date_from}_{self.date_to}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': self._name,
            'res_id': self.id,
        })

        # Return download action
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

