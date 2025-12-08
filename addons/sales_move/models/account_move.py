from odoo import models, fields, api
from datetime import date
from odoo.tools import float_is_zero, float_compare

class AccountMove(models.Model):
    _inherit = 'account.move'

    is_invoice_date_past = fields.Boolean(
        compute="_compute_is_invoice_date_past", store=True
    )
    is_date_past = fields.Boolean(
        compute="_compute_is_date_past", store=True
    )
    manual_quantity_so = fields.Float(string="Manual Quantity SO")
    price_currency = fields.Monetary(string="Price Currency", currency_field='currency_id')
    total_unfixed_balance = fields.Monetary(
        string='Total Unfixed Balance',
        compute='_compute_total_unfixed_balance',
        store=True,
        currency_field='currency_id'
    )

    @api.depends('invoice_line_ids.unfixed_balance')
    def _compute_total_unfixed_balance(self):
        for move in self:
            move.total_unfixed_balance = sum(move.invoice_line_ids.mapped('unfixed_balance'))

    @api.depends('invoice_date')
    def _compute_is_invoice_date_past(self):
        for order in self:
            order.is_invoice_date_past = order.invoice_date and order.invoice_date < date.today()

    @api.depends('date')
    def _compute_is_date_past(self):
        for order in self:
            order.is_date_past = order.date and order.date < date.today()

    @api.model
    def _get_outstanding_info_JSON(self):
        # Get the sales order from the invoice
        sales_order = self.env['sale.order'].search([('name', '=', self.invoice_origin)], limit=1)
        if not sales_order:
            return super()._get_outstanding_info_JSON()  # fallback to default

        outstanding_credits = []
        for payment in sales_order.selected_payment_ids:
            # Only include payments that are linked to this sales order
            if (
                payment.state in ('posted', 'reconciled')
                and payment.amount_residual > 0
                and payment.sales_order_id and payment.sales_order_id.id == sales_order.id
            ):
                outstanding_credits.append({
                    'journal_name': payment.journal_id.name,
                    'amount': payment.amount_residual,
                    'currency': payment.currency_id.name,
                    'payment_id': payment.id,
                    'payment_date': payment.payment_date,
                    'ref': payment.ref,
                })

        if not outstanding_credits:
            # No payments for this sales order, fallback to default
            return super()._get_outstanding_info_JSON()

        # Only show these payments, do not merge with others
        return {
            'title': 'Outstanding credits',
            'outstanding': True,
            'content': outstanding_credits,
        }

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    unfixed_balance = fields.Monetary(
        string='Unfixed Balance',
        compute='_compute_unfixed_balance',
        store=True,
        currency_field='currency_id'
    )

    @api.depends('price_subtotal', 'move_id.payment_id.amount')
    def _compute_unfixed_balance(self):
        for line in self:
            if line.move_id.move_type == 'out_invoice':
                # Get the total payments for this invoice
                total_payments = sum(line.move_id.payment_id.mapped('amount'))
                # Calculate unfixed balance as the difference between subtotal and payments
                line.unfixed_balance = line.price_subtotal - total_payments
            else:
                line.unfixed_balance = 0.0

    def _stock_account_get_anglo_saxon_price_unit(self):
        """
        Override to use product_cost from stock.move.line instead of default Odoo calculation.
        
        ORIGINAL ODOO COGS CALCULATION:
        The default Odoo method uses product._compute_average_price() which:
        1. Gets stock valuation layers (SVL) from stock moves
        2. Consumes SVLs based on FIFO/AVCO cost method
        3. Uses the cost that was stored in SVL when stock was delivered
        4. Falls back to product.standard_price if not enough SVLs
        
        OUR CUSTOM CALCULATION:
        We use product_cost from stock.move.line which comes from manufacturing orders.
        This gives us the actual cost per lot that was manufactured, ensuring:
        - Stock delivery entry uses: sum(product_cost from move lines) / quantity_done
        - Invoice COGS entry uses: same calculation
        - Both entries reconcile automatically in Stock Interim account
        """
        self.ensure_one()
        # If no product, return default price unit
        if not self.product_id:
            return super(AccountMoveLine, self)._stock_account_get_anglo_saxon_price_unit()
        # Get the sale order line from the invoice line
        so_line = self.sale_line_ids and self.sale_line_ids[-1] or False
        if not so_line:
            # Fall back to default if no sale order line
            return super(AccountMoveLine, self)._stock_account_get_anglo_saxon_price_unit()
        # Check if this is a refund (reversing entry)
        down_payment = self.move_id.invoice_line_ids.filtered(
            lambda line: any(line.sale_line_ids.mapped('is_downpayment'))
        )
        is_line_reversing = False
        if self.move_id.move_type == 'out_refund' and not down_payment:
            is_line_reversing = True

        # Get quantity to invoice in product UOM
        qty_to_invoice = self.product_uom_id._compute_quantity(
            self.quantity, self.product_id.uom_id
        )
        if self.move_id.move_type == 'out_refund' and down_payment:
            qty_to_invoice = -qty_to_invoice

        # Get already posted invoices for this sale order line
        account_moves = so_line.invoice_lines.move_id.filtered(
            lambda m: m.state == 'posted' and bool(m.reversed_entry_id) == is_line_reversing
        )
        # Calculate already invoiced quantity and value
        posted_cogs = account_moves.line_ids.filtered(
            lambda l: l.display_type == 'cogs' 
            and l.product_id == self.product_id 
            and l.balance > 0
        )
        qty_invoiced = 0.0
        value_invoiced = 0.0
        product_uom = self.product_id.uom_id
        for line in posted_cogs:
            if (float_compare(line.quantity, 0, precision_rounding=product_uom.rounding) 
                and line.move_id.move_type == 'out_refund' 
                and any(line.move_id.invoice_line_ids.sale_line_ids.mapped('is_downpayment'))):
                qty_invoiced += line.product_uom_id._compute_quantity(
                    abs(line.quantity), line.product_id.uom_id
                )
            else:
                qty_invoiced += line.product_uom_id._compute_quantity(
                    line.quantity, line.product_id.uom_id
                )
        
        value_invoiced = sum(posted_cogs.mapped('balance'))
        
        # Subtract reversal COGS
        reversal_cogs = posted_cogs.move_id.reversal_move_id.line_ids.filtered(
            lambda l: l.display_type == 'cogs' 
            and l.product_id == self.product_id 
            and l.balance > 0
        )
        
        for line in reversal_cogs:
            if (float_compare(line.quantity, 0, precision_rounding=product_uom.rounding) 
                and line.move_id.move_type == 'out_refund' 
                and any(line.move_id.invoice_line_ids.sale_line_ids.mapped('is_downpayment'))):
                qty_invoiced -= line.product_uom_id._compute_quantity(
                    abs(line.quantity), line.product_id.uom_id
                )
            else:
                qty_invoiced -= line.product_uom_id._compute_quantity(
                    line.quantity, line.product_id.uom_id
                )
        
        value_invoiced -= sum(reversal_cogs.mapped('balance'))
        
        # Get stock moves related to this sale order line
        # Filter for moves that are done and delivered to customer
        stock_moves = so_line.move_ids.filtered(
            lambda m: m.state == 'done' 
            and m.location_dest_id.usage == 'customer'
        )
        
        if not stock_moves:
            # Fall back to default if no stock moves
            return super(AccountMoveLine, self)._stock_account_get_anglo_saxon_price_unit()
        
        # Calculate total cost and quantity from stock moves
        # We need to consider only the moves that haven't been fully invoiced yet
        total_cost = 0.0
        total_quantity = 0.0
        
        # Sort moves by date to process in order
        sorted_moves = stock_moves.sorted('date')
        
        remaining_qty_to_invoice = qty_to_invoice
        remaining_qty_invoiced = qty_invoiced
        
        for move in sorted_moves:
            # Get the quantity in product UOM for this move (quantity actually delivered)
            move_qty = move.product_uom._compute_quantity(
                move.quantity_done, move.product_id.uom_id
            )
            
            # Skip if this move was already fully invoiced
            if remaining_qty_invoiced >= move_qty:
                remaining_qty_invoiced -= move_qty
                continue
            
            # Calculate how much of this move is available for invoicing
            available_qty = move_qty - remaining_qty_invoiced
            remaining_qty_invoiced = 0.0  # Reset after first move
            
            if float_is_zero(available_qty, precision_rounding=product_uom.rounding):
                continue
            
            # Get custom cost using multiple fallback strategies
            # This tries: product_cost -> mo_purchase_cost -> direct MO lookup -> total_purchase_cost
            total_move_cost, has_cost = move._get_custom_cost_from_move_lines()
            
            if has_cost and not float_is_zero(move_qty, precision_rounding=product_uom.rounding):
                # Calculate cost per unit: total_move_cost / quantity delivered
                cost_per_unit = total_move_cost / move_qty
                
                # Add to totals based on how much we need to invoice
                qty_to_use = min(available_qty, remaining_qty_to_invoice)
                if qty_to_use > 0:
                    # Calculate cost for the quantity to invoice
                    cost_to_use = cost_per_unit * qty_to_use
                    total_cost += cost_to_use
                    total_quantity += qty_to_use
                    remaining_qty_to_invoice -= qty_to_use
                    
                    if float_is_zero(remaining_qty_to_invoice, precision_rounding=product_uom.rounding):
                        break
        
        # Calculate average price unit
        if not float_is_zero(total_quantity, precision_rounding=product_uom.rounding):
            average_price_unit = total_cost / total_quantity
        else:
            # If no quantity available, fall back to default
            return super(AccountMoveLine, self)._stock_account_get_anglo_saxon_price_unit()
        
        # Convert to invoice line's UOM
        price_unit = self.product_id.uom_id.with_company(self.company_id)._compute_price(
            average_price_unit, self.product_uom_id
        )
        
        return price_unit 