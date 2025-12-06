# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class UpdateCogsWizard(models.TransientModel):
    _name = 'update.cogs.wizard'
    _description = 'Update COGS and Stock Interim Entries'

    @api.model
    def _get_default_message(self):
        return _(
            "This wizard will update:\n"
            "1. Stock Valuation Layers (SVL) with correct cost from product_cost\n"
            "2. Stock delivery accounting entries (Stock Interim credit)\n"
            "3. Invoice COGS entries (Stock Interim debit)\n\n"
            "Note: Only entries for stock moves with product_cost in move lines will be updated."
        )

    message = fields.Text(string="Information", default=_get_default_message, readonly=True)
    update_svl = fields.Boolean(string="Update Stock Valuation Layers", default=True)
    update_delivery_entries = fields.Boolean(string="Update Stock Delivery Entries", default=True)
    update_invoice_cogs = fields.Boolean(string="Update Invoice COGS Entries", default=True)

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
        
        for move in stock_moves:
            # Get total cost from move lines
            move_line_costs = move.move_line_ids.mapped('product_cost')
            total_move_cost = sum(move_line_costs) if move_line_costs else 0.0
            
            if float_is_zero(total_move_cost, precision_rounding=move.product_id.uom_id.rounding):
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
            
            # 2. Update Stock Delivery Accounting Entries
            if self.update_delivery_entries:
                account_moves = move.account_move_ids.filtered(
                    lambda m: m.state == 'posted'
                )
                for acc_move in account_moves:
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
                                for line in interim_lines:
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
                                    for val_line in valuation_lines:
                                        if val_line.debit > 0:  # Debit side
                                            new_balance = abs(quantity_done * correct_unit_cost)
                                            if abs(val_line.balance - new_balance) > 0.01:
                                                val_line.write({'balance': new_balance})
                                acc_move.action_post()
                                updated_account_moves |= acc_move
                            except Exception as e:
                                # If update fails, try to repost
                                if acc_move.state == 'draft':
                                    acc_move.action_post()
                                raise UserError(_("Error updating entry %s: %s") % (acc_move.name, str(e)))
            
            # 3. Update Invoice COGS Entries
            if self.update_invoice_cogs:
                # Get sale order line from this move
                so_line = move.sale_line_id
                if so_line:
                    # Get all invoices for this sale order line
                    invoices = so_line.invoice_lines.mapped('move_id').filtered(
                        lambda m: m.state == 'posted' and m.move_type in ('out_invoice', 'out_refund')
                    )
                    stock_output_account = move.product_id.categ_id.property_stock_account_output_categ_id
                    for invoice in invoices:
                        # Get COGS lines for this product
                        cogs_lines = invoice.line_ids.filtered(
                            lambda l: l.display_type == 'cogs' 
                            and l.product_id == move.product_id
                        )
                        if cogs_lines:
                            try:
                                invoice.button_draft()
                                for cogs_line in cogs_lines:
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
                            except Exception as e:
                                # If update fails, try to repost
                                if invoice.state == 'draft':
                                    invoice.action_post()
                                raise UserError(_("Error updating invoice %s: %s") % (invoice.name, str(e)))
        
        # Prepare result message
        result_msg = _("Update completed:\n")
        if self.update_svl:
            result_msg += _("- Updated %d Stock Valuation Layer(s)\n") % len(updated_svls)
        if self.update_delivery_entries:
            result_msg += _("- Updated %d Stock Delivery Entry/ies\n") % len(updated_account_moves)
        if self.update_invoice_cogs:
            result_msg += _("- Updated %d Invoice COGS Entry/ies\n") % len(updated_invoices)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Update Complete'),
                'message': result_msg,
                'type': 'success',
                'sticky': False,
            }
        }

