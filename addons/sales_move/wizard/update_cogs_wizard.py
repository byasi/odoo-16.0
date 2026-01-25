# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, MissingError
from odoo.tools import float_is_zero
import logging

_logger = logging.getLogger(__name__)


class UpdateCogsWizard(models.TransientModel):
    _name = 'update.cogs.wizard'
    _description = 'Update COGS and Stock Interim Entries'

    @api.model
    def _get_default_message(self):
        return _(
            "This wizard will update:\n"
            "1. Stock Valuation Layers (SVL) with correct cost from product_cost\n"
            "2. Stock delivery accounting entries (Stock Interim credit)\n"
            "3. Invoice COGS entries (Stock Interim debit)\n"
            "4. Update all invoices to have product_cost from sale order lines\n\n"
            "Note: Only entries for stock moves with product_cost in move lines will be updated."
        )

    message = fields.Text(string="Information", default=_get_default_message, readonly=True)
    update_svl = fields.Boolean(string="Update Stock Valuation Layers", default=True)
    update_delivery_entries = fields.Boolean(string="Update Stock Delivery Entries", default=True)
    update_invoice_cogs = fields.Boolean(string="Update Invoice COGS Entries", default=True)
    update_invoice_product_cost = fields.Boolean(string="Update All Invoices Product Cost", default=True)

    def action_update_entries(self):
        """
        Update existing entries to use product_cost from stock.move.line
        """
        self.ensure_one()
        
        # Find all done outgoing stock moves that have move lines with product_cost
        stock_moves = self.env['stock.move'].search([
            ('state', '=', 'done'),
            ('location_dest_id.usage', '=', 'customer'),
            ('move_line_ids.product_cost', '>', 0),
        ])
        
        if not stock_moves:
            raise UserError(_("No stock moves found with product_cost in move lines."))
        
        updated_svls = self.env['stock.valuation.layer']
        updated_account_moves = self.env['account.move']
        updated_invoices = self.env['account.move']
        updated_invoice_lines = self.env['account.move.line']
        invoices_to_repost_for_product_cost = self.env['account.move']
        skipped_entries = []
        
        for move in stock_moves:
            # Get total cost using multiple fallback strategies
            # This tries: product_cost -> mo_purchase_cost -> direct MO lookup -> total_purchase_cost
            total_move_cost, has_cost = move._get_custom_cost_from_move_lines()
            
            if not has_cost or float_is_zero(total_move_cost, precision_rounding=move.product_id.uom_id.rounding):
                continue
            
            # Get quantity in product UOM
            quantity_done = move.product_uom._compute_quantity(
                move.quantity_done, move.product_id.uom_id
            )
            
            if float_is_zero(quantity_done, precision_rounding=move.product_id.uom_id.rounding):
                continue
            
            # Calculate correct unit cost
            correct_unit_cost = total_move_cost / quantity_done
            
            # 1. Update Stock Valuation Layers
            if self.update_svl:
                svls = move.stock_valuation_layer_ids.filtered(
                    lambda s: s.quantity < 0  # Outgoing layers have negative quantity
                )
                for svl in svls:
                    # Check if record still exists
                    if not svl.exists():
                        skipped_entries.append(_("SVL %s (deleted)") % svl.id)
                        continue
                    try:
                        if abs(svl.unit_cost - correct_unit_cost) > 0.01:  # Only update if different
                            currency = move.company_id.currency_id
                            # Update unit_cost and recalculate value
                            # Note: quantity is negative for out moves
                            new_value = currency.round(abs(svl.quantity) * correct_unit_cost)
                            # Value should be negative for out moves
                            if svl.quantity < 0:
                                new_value = -new_value
                            svl.write({
                                'unit_cost': correct_unit_cost,
                                'value': new_value,
                            })
                            updated_svls |= svl
                    except (MissingError, Exception) as e:
                        _logger.warning("Error updating SVL %s: %s", svl.id, str(e))
                        skipped_entries.append(_("SVL %s: %s") % (svl.id, str(e)))
                        continue
            
            # 2. Update Stock Delivery Accounting Entries
            if self.update_delivery_entries:
                account_moves = move.account_move_ids.filtered(
                    lambda m: m.state == 'posted'
                )
                for acc_move in account_moves:
                    # Check if record still exists
                    if not acc_move.exists():
                        skipped_entries.append(_("Account Move %s (deleted)") % acc_move.name)
                        continue
                    # Find lines with Stock Interim (Delivered) account
                    stock_output_account = move.product_id.categ_id.property_stock_account_output_categ_id
                    if stock_output_account:
                        interim_lines = acc_move.line_ids.filtered(
                            lambda l: l.account_id == stock_output_account
                        )
                        if interim_lines:
                            # Unpost, update, and repost
                            try:
                                acc_move.button_draft()
                                # Check again after unposting - records might have changed
                                if not acc_move.exists():
                                    skipped_entries.append(_("Account Move %s (deleted after unpost)") % acc_move.name)
                                    continue
                                for line in interim_lines.exists():  # Filter out deleted lines
                                    # Recalculate balance based on correct cost
                                    if line.credit > 0:  # Credit side (Stock Interim)
                                        new_balance = -abs(quantity_done * correct_unit_cost)
                                        if abs(line.balance - new_balance) > 0.01:
                                            line.write({'balance': new_balance})
                                # Also update the corresponding debit line (Stock Valuation)
                                stock_valuation_account = move.product_id.categ_id.property_stock_valuation_account_id
                                if stock_valuation_account:
                                    valuation_lines = acc_move.line_ids.filtered(
                                        lambda l: l.account_id == stock_valuation_account
                                    )
                                    for val_line in valuation_lines.exists():  # Filter out deleted lines
                                        if val_line.debit > 0:  # Debit side
                                            new_balance = abs(quantity_done * correct_unit_cost)
                                            if abs(val_line.balance - new_balance) > 0.01:
                                                val_line.write({'balance': new_balance})
                                acc_move.action_post()
                                updated_account_moves |= acc_move
                            except (MissingError, Exception) as e:
                                # If update fails, try to repost if still in draft
                                try:
                                    if acc_move.exists() and acc_move.state == 'draft':
                                        acc_move.action_post()
                                except:
                                    pass
                                _logger.warning("Error updating account move %s: %s", acc_move.name, str(e))
                                skipped_entries.append(_("Account Move %s: %s") % (acc_move.name, str(e)))
                                continue
            
            # 3. Update Invoice COGS Entries
            if self.update_invoice_cogs:
                # Get sale order line from this move
                so_line = move.sale_line_id
                if so_line and so_line.exists():
                    # Get all invoices for this sale order line
                    invoices = so_line.invoice_lines.mapped('move_id').filtered(
                        lambda m: m.state == 'posted' and m.move_type in ('out_invoice', 'out_refund')
                    )
                    stock_output_account = move.product_id.categ_id.property_stock_account_output_categ_id
                    for invoice in invoices:
                        # Check if record still exists
                        if not invoice.exists():
                            skipped_entries.append(_("Invoice %s (deleted)") % invoice.name)
                            continue
                        # Get COGS lines for this product
                        cogs_lines = invoice.line_ids.filtered(
                            lambda l: l.display_type == 'cogs' 
                            and l.product_id == move.product_id
                        )
                        if cogs_lines:
                            try:
                                invoice.button_draft()
                                # Check again after unposting
                                if not invoice.exists():
                                    skipped_entries.append(_("Invoice %s (deleted after unpost)") % invoice.name)
                                    continue
                                for cogs_line in cogs_lines.exists():  # Filter out deleted lines
                                    # Recalculate based on correct cost
                                    qty = cogs_line.product_uom_id._compute_quantity(
                                        cogs_line.quantity, cogs_line.product_id.uom_id
                                    )
                                    new_balance = qty * correct_unit_cost
                                    
                                    # COGS expense line should be debit (positive balance)
                                    # Stock Interim line should be credit (negative balance)
                                    if stock_output_account and cogs_line.account_id == stock_output_account:
                                        # Stock Interim line
                                        if abs(cogs_line.balance + new_balance) > 0.01:
                                            cogs_line.write({'balance': -new_balance})
                                    else:
                                        # Expense line
                                        if abs(cogs_line.balance - new_balance) > 0.01:
                                            cogs_line.write({'balance': new_balance})
                                invoice.action_post()
                                updated_invoices |= invoice
                            except (MissingError, Exception) as e:
                                # If update fails, try to repost if still in draft
                                try:
                                    if invoice.exists() and invoice.state == 'draft':
                                        invoice.action_post()
                                except:
                                    pass
                                _logger.warning("Error updating invoice %s: %s", invoice.name, str(e))
                                skipped_entries.append(_("Invoice %s: %s") % (invoice.name, str(e)))
                                continue
        
        # 4. Update All Invoices Product Cost
        if self.update_invoice_product_cost:
            # Find all invoice lines that:
            # - Are part of customer invoices (out_invoice, out_refund)
            # - Have a sale order line linked
            # - Have product_cost = 0 or missing
            invoice_lines = self.env['account.move.line'].search([
                ('move_id.move_type', 'in', ('out_invoice', 'out_refund')),
                ('sale_line_ids', '!=', False),
                ('product_id', '!=', False),
                '|',
                ('product_cost', '=', 0.0),
                ('product_cost', '=', False),
            ])
            
            for inv_line in invoice_lines:
                # Get the related sale order line
                so_line = inv_line.sale_line_ids and inv_line.sale_line_ids[0] or False
                if so_line and so_line.product_cost and not float_is_zero(so_line.product_cost, precision_rounding=so_line.product_id.uom_id.rounding):
                    try:
                        # Check if invoice is posted - if so, we need to unpost, update, and repost
                        invoice = inv_line.move_id
                        was_posted = invoice.state == 'posted'
                        
                        if was_posted:
                            invoice.button_draft()
                            # Check if invoice still exists after unposting
                            if not invoice.exists():
                                skipped_entries.append(_("Invoice %s (deleted after unpost)") % invoice.name)
                                continue
                        
                        # Update product_cost on the invoice line
                        inv_line.write({'product_cost': so_line.product_cost})
                        updated_invoice_lines |= inv_line
                        
                        # Track invoice for reposting if it was posted
                        if was_posted and invoice.exists():
                            invoices_to_repost_for_product_cost |= invoice
                            
                    except (MissingError, Exception) as e:
                        # If update fails, try to repost if still in draft
                        try:
                            if invoice.exists() and invoice.state == 'draft':
                                invoice.action_post()
                        except:
                            pass
                        _logger.warning("Error updating invoice line %s (Invoice %s): %s", inv_line.id, inv_line.move_id.name, str(e))
                        skipped_entries.append(_("Invoice Line %s (Invoice %s): %s") % (inv_line.id, inv_line.move_id.name, str(e)))
                        continue
            
            # Repost all invoices that were unposted
            for invoice in invoices_to_repost_for_product_cost:
                try:
                    if invoice.exists() and invoice.state == 'draft':
                        invoice.action_post()
                        updated_invoices |= invoice
                except (MissingError, Exception) as e:
                    _logger.warning("Error reposting invoice %s: %s", invoice.name, str(e))
                    skipped_entries.append(_("Invoice %s (repost failed): %s") % (invoice.name, str(e)))
        
        # Prepare result message
        result_msg = _("Update completed:\n")
        if self.update_svl:
            result_msg += _("- Updated %d Stock Valuation Layer(s)\n") % len(updated_svls)
        if self.update_delivery_entries:
            result_msg += _("- Updated %d Stock Delivery Entry/ies\n") % len(updated_account_moves)
        if self.update_invoice_cogs:
            result_msg += _("- Updated %d Invoice COGS Entry/ies\n") % len(updated_invoices)
        if self.update_invoice_product_cost:
            result_msg += _("- Updated %d Invoice Line(s) with Product Cost\n") % len(updated_invoice_lines)
            if invoices_to_repost_for_product_cost:
                result_msg += _("- Reposted %d Invoice(s) to recalculate COGS\n") % len(invoices_to_repost_for_product_cost)
        
        if skipped_entries:
            result_msg += _("\nSkipped entries (deleted or error):\n")
            for entry in skipped_entries[:10]:  # Show first 10 skipped entries
                result_msg += _("- %s\n") % entry
            if len(skipped_entries) > 10:
                result_msg += _("- ... and %d more\n") % (len(skipped_entries) - 10)
        
        # Use warning type if there were skipped entries, success otherwise
        msg_type = 'warning' if skipped_entries else 'success'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Update Complete'),
                'message': result_msg,
                'type': msg_type,
                'sticky': False,
            }
        }

