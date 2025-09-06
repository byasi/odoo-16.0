from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round
import math
from datetime import date
import logging

_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'
    currency_id = fields.Many2one('res.currency', string="Currency", invisible=True)
    state = fields.Selection(
        selection_add=[('unfixed', 'Unfixed')],  # Add new state
        ondelete={'unfixed': 'set default'}
    )
    purchase_method = fields.Selection([
        ('purchase_1', 'Purchase 1'),
        ('purchase_2', 'Purchase 2')
    ], string="Purchase Method", default='purchase_1', required=True)
    market_price = fields.Monetary(string="Market Price", currency_field='market_price_currency', required=True)
    product_price = fields.Monetary(string="Product Price")
    deduction_head = fields.Float(string="Deduction Head")
    additions = fields.Float(string="Additions")
    market_price_currency = fields.Many2one('res.currency', string="Market Price Currency",
                                            default=lambda self: self.env.ref('base.USD').id)
    discount = fields.Float(string="Discount/additions")
    net_price = fields.Monetary(
        string="Net Market Price",
        compute="_compute_net_price",
        currency_field='market_price_currency',
        store=True
    )
    material_unit = fields.Many2one('uom.uom', string="Market Price Unit",
                                    default=lambda self: self.env.ref('uom.product_uom_oz').id)
    material_unit_input = fields.Many2one('uom.uom', string="Material Unit Input",
                                          default=lambda self: self.env.ref('uom.product_uom_gram').id)
    date_approve = fields.Datetime(
        string="Order Deadline",
        readonly=False # Ensure it's editable at all times
    )

    transaction_currency = fields.Many2one('res.currency', string="Transaction Currency",
                                           default=lambda self: self.env.ref('base.USD').id)
    
    @api.depends('purchase_method')
    def _compute_transaction_unit(self):
        for record in self:
            if record.purchase_method == 'purchase_2':
                record.transaction_unit = self.env.ref('uom.product_uom_gram').id
            else:
                record.transaction_unit = self.env.ref('uom.product_uom_ton').id

    transaction_unit = fields.Many2one('uom.uom', string="Transaction Unit",
                                     compute='_compute_transaction_unit',
                                     store=True)
    
    x_factor = fields.Float(string="Xfactor", compute='_compute_x_factor', store=True)
    # @api.model
    # def _default_x_factor(self):
    #     # Access the current company from the context
    #     current_company_id = self.env.context.get('allowed_company_ids', [self.env.company.id])[0]
    #     current_company = self.env['res.company'].browse(current_company_id)

    #     if current_company.name == 'PEX-DRC':
    #         return 100
    #     return 92 
    net_total = fields.Monetary(string="Net Total", currency_field='transaction_currency', compute="_compute_net_total",
                                store=True)
    # deductions = fields.Monetary(string="Deductions",currency_field='transaction_currency', related="total_deductions")
    deductions = fields.Monetary(string="Deductions", currency_field='transaction_currency')
    company_currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True, string="Company Currency"
    )
    transaction_price_per_unit = fields.Monetary(string="Transaction Price per Unit",
                                                 currency_field='transaction_currency',
                                                 compute="_compute_transaction_price_per_unit", store=True)
    original_market_price = fields.Monetary(string="Original Market Price", currency_field='company_currency_id')
    currency = fields.Many2one('res.currency', string="Currency", default=lambda self: self.env.ref('base.UGX').id)
    partner_street = fields.Char(related='partner_id.street', string="Street", readonly=True)
    partner_city = fields.Char(related='partner_id.city', string="City", readonly=True)
    partner_zip = fields.Char(related='partner_id.zip', string="ZIP", readonly=True)
    partner_country = fields.Many2one(related='partner_id.country_id', string="Country", readonly=True)
    partner_contact = fields.Char(related='partner_id.phone', string="Contact", readonly=True)
    total_with_weights = fields.Float(
        string='Total RM',
        compute='_compute_totals',
        store=True
    )
    total_without_weights = fields.Float(
        string='Total TA',
        compute='_compute_totals',
        store=True
    )
    total_without_weights_ugx = fields.Float(
        string='Total TA UGX',
        compute='_compute_totals',
        store=True
    )
    is_date_approve_past = fields.Boolean(
        compute="_compute_is_date_approve_past", store=True
    )
    total_first_process = fields.Float(
        string='Total First Process',
        compute='_compute_totals',
        store=True
    )
   

    def action_create_invoice(self):
        """ Override the bill creation to copy the Order Deadline as the Bill Date. """
        res = super(PurchaseOrder, self).action_create_invoice()

        for bill in self.invoice_ids:
            if self.date_approve:  # Check if Order Deadline exists
                bill.invoice_date = self.date_approve
                bill.date = self.date_approve
        return res


    @api.depends('date_approve')
    def _compute_is_date_approve_past(self):
        for order in self:
            order.is_date_approve_past = order.date_approve and order.date_approve.date() < date.today()


    @api.depends('order_line', 'order_line.first_process_wt', 'order_line.second_process_wt',
                 'order_line.price_subtotal')
    def _compute_totals(self):
        for order in self:
            total_with_weights = 0
            total_without_weights = 0
            total_without_weights_ugx = 0
            total_first_process = 0
            for line in order.order_line:
                if line.first_process_wt > 0 and line.second_process_wt > 0:
                    total_with_weights += line.price_subtotal
                    total_first_process += line.first_process_wt
                else:
                    total_without_weights += line.price_subtotal
                    total_without_weights_ugx += line.price_unit
                    total_first_process += line.first_process_wt
            order.total_with_weights = total_with_weights
            order.total_without_weights = total_without_weights
            order.total_without_weights_ugx = total_without_weights_ugx
            order.total_first_process = total_first_process
    def custom_round_down(self, value):
        scaled_value = value * 100
        rounded_down_value = math.floor(scaled_value) / 100
        return rounded_down_value

    @api.depends('market_price', 'discount')
    def _compute_net_price(self):
        for order in self:
            if order.market_price and order.discount:
                net_price = order.market_price + order.discount
                order.net_price = self.custom_round_down(net_price)
            else:
                order.net_price = self.custom_round_down(order.market_price) if order.market_price else 0.

    @api.depends('convention_market_unit', 'net_price', 'transaction_currency', 'market_price_currency', 'purchase_method')
    def _compute_transaction_price_per_unit(self):
        for order in self:
            if order.convention_market_unit and order.net_price and order.transaction_currency:
                converted_market_price = order.market_price_currency._convert(
                    order.net_price,
                    order.transaction_currency,
                    order.company_id,
                    order.date_order or fields.Date.today()
                )
                # Use different divisor based on purchase method
                divisor = 31.1034786 if order.purchase_method == 'purchase_2' else 3
                transaction_price_per_unit = converted_market_price / divisor
                order.transaction_price_per_unit = self.custom_round_down(transaction_price_per_unit)
            else:
                order.transaction_price_per_unit = 0.0

    @api.depends('order_line.amount', 'deductions', 'transaction_currency')
    def _compute_net_total(self):
        for order in self:
            total = sum(line.amount for line in order.order_line)
            # Calculate the net total after deducting the converted deduction value
            net_total = total + order.deductions
            order.net_total = self.custom_round_down(net_total)

    @api.model
    def _compute_formula_selection(self):
        ICPSudo = self.env['ir.config_parameter'].sudo()
        method_1 = ICPSudo.get_param('purchase_move.method_1', default='')
        method_2 = ICPSudo.get_param('purchase_move.method_2', default='')
        method_3 = ICPSudo.get_param('purchase_move.method_3', default='')
        return [
            ('method_1', method_1),
            ('method_2', method_2),
            ('method_3', method_3),
        ]

    formula = fields.Selection(
        selection='_compute_formula_selection',
        string='Formula',
        default='method_1',
        readonly=True
    )
    convention_market_unit = fields.Float(
        string="Conversion Market Unit",
        compute="_compute_convention_market_unit",
        store=True
    )

    @api.depends('material_unit', 'transaction_unit')
    def _compute_convention_market_unit(self):
        for record in self:
            if record.material_unit and record.transaction_unit:
                record.convention_market_unit = self.custom_round_down(
                    record.transaction_unit._compute_quantity(1, record.material_unit)
                )
            else:
                record.convention_market_unit = 0.0

    @api.onchange('market_price_currency')
    def _onchange_market_price_currency(self):
        for record in self:
            if record.market_price_currency:
                if not record.original_market_price:
                    # Store the original market price in the company's base currency
                    record.original_market_price = record.market_price_currency._convert(
                        record.market_price,
                        record.company_currency_id,
                        record.company_id,
                        record.date_order or fields.Date.today()
                    )
                # Convert the original market price to the selected market price currency
                record.market_price = record.company_currency_id._convert(
                    record.original_market_price,
                    record.market_price_currency,
                    record.company_id,
                    record.date_order or fields.Date.today()
                )

    amount_untaxed = fields.Monetary(string='Untaxed Amount', store=True, readonly=True, compute='_amount_all',
                                     tracking=True)
    tax_totals = fields.Binary(compute='_compute_tax_totals', exportable=False)
    amount_tax = fields.Monetary(string='Taxes', store=True, readonly=True, compute='_amount_all')
    amount_total = fields.Monetary(string='Total', store=True, readonly=True, compute='_amount_all')

    @api.depends('order_line.price_total', 'order_line.current_amount', 'deductions', 'transaction_currency', 'current_market_price')
    def _amount_all(self):
        for order in self:
            order_lines = order.order_line.filtered(lambda x: not x.display_type)
            # Check if current market price is set and not zero
            if order.current_market_price and not float_is_zero(order.current_market_price, precision_digits=2):
                # Use current amounts based on current market price
                amount_untaxed = sum(order_lines.mapped('current_amount'))
                amount_tax = sum(order_lines.mapped('price_tax'))  # Tax calculation remains the same
                # Convert amounts to transaction currency
                order.amount_untaxed = self.custom_round_down(
                    order.currency_id._convert(
                        amount_untaxed,
                        order.transaction_currency,
                        order.company_id,
                        order.date_order or fields.Date.today()
                    )
                )
                order.amount_tax = self.custom_round_down(
                    order.currency_id._convert(
                        amount_tax,
                        order.transaction_currency,
                        order.company_id,
                        order.date_order or fields.Date.today()
                    )
                )
                
                # Calculate total using current amounts
                total = (order.amount_untaxed + order.amount_tax) + order.deductions
                order.amount_total = self.custom_round_down(total)
            else:
                # Use original amounts based on original market price
                amount_untaxed = sum(order_lines.mapped('price_subtotal'))
                amount_tax = sum(order_lines.mapped('price_tax'))

                # Convert amounts to transaction currency
                order.amount_untaxed = self.custom_round_down(
                    order.currency_id._convert(
                        amount_untaxed,
                        order.transaction_currency,
                        order.company_id,
                        order.date_order or fields.Date.today()
                    )
                )
                order.amount_tax = self.custom_round_down(
                    order.currency_id._convert(
                        amount_tax,
                        order.transaction_currency,
                        order.company_id,
                        order.date_order or fields.Date.today()
                    )
                )

                total = (order.amount_untaxed + order.amount_tax) + order.deductions
                order.amount_total = self.custom_round_down(total)

    # deductions tab here
    deduction_ids = fields.One2many('purchase.order.deductions', 'order_id', string="Deductions")
    deduction_lines = fields.One2many('purchase.order.deductions', 'order_id', string='Deductions')
    total_deductions = fields.Monetary(string='Total Deductions', currency_field='currency_id',
                                       compute="_compute_total_deductions")

    @api.depends('deduction_ids.transaction_currency_amount')
    def _compute_total_deductions(self):
        for order in self:
            total = 0.0
            for deduction in order.deduction_ids:
                total += deduction.transaction_currency_amount
            order.total_deductions = total

    # End of deductions tab

    @api.constrains('market_price')
    def _check_market_price(self):
        for order in self:
            if float_is_zero(order.market_price, precision_digits=2):
                raise ValidationError(_(
                    "Market Price is required and cannot be zero.\n"
                    "Please set a valid Market Price before saving."
                ))

    @api.depends('purchase_method')
    def _compute_x_factor(self):
        for record in self:
            if record.purchase_method == 'purchase_2':
                record.x_factor = 100
            else:
                record.x_factor = 92

    def action_convert_to_purchase_order(self):
        """ Convert 'Unfixed' to 'Purchase Order' state."""
        for order in self:
            if order.state == 'unfixed':
                order.state = 'purchase'
                # Trigger purchase cost recalculation when converting
                order.recalculate_purchase_cost_chain()

    def action_back_to_unfixed(self):
        """Convert 'Purchase Order' back to 'unfixed'."""
        for order in self:
            if order.state == 'purchase':
                order.state = 'unfixed'

    @api.depends('selected_payment_ids')
    def _compute_payment_amount(self):
        for record in self:
            total_amount = 0.0
            for payment in record.selected_payment_ids:
                if payment.currency_id != record.currency_id:
                    # Convert payment amount to the base currency (or the currency of the record)
                    total_amount += payment.currency_id._convert(
                        payment.amount,
                        record.currency_id,
                        record.company_id,
                        payment.date or fields.Date.context_today(record)
                    )
                else:
                    total_amount += payment.amount
            record.payment_amount = total_amount

    @api.depends('amount_total', 'payment_amount')
    def _compute_unfixed_balance(self):
        for order in self:
            order.unfixed_balance = abs(order.amount_total - order.payment_amount)

# Unfixed  logic
    current_net_payable = fields.Monetary(
        string="Current Net Payable",
        currency_field='transaction_currency',
        compute="_compute_current_net_payable",
        store=True
    )

    @api.depends('current_net_total', 'payment_amount')
    def _compute_current_net_payable(self):
        for order in self:
            if order.current_net_total is not None and order.payment_amount is not None:
                order.current_net_payable = order.current_net_total - order.payment_amount
            else:
                order.current_net_payable = 0.0

    # Add the missing current_net_total field
    current_net_total = fields.Monetary(
        string="Current Net Total",
        currency_field='transaction_currency',
        compute="_compute_current_net_total",
        store=True
    )

    @api.depends('order_line.current_amount', 'deductions', 'transaction_currency')
    def _compute_current_net_total(self):
        for order in self:
            total = sum(line.current_amount for line in order.order_line)
            # Calculate the current net total after deducting the converted deduction value
            current_net_total = total + order.deductions
            order.current_net_total = self.custom_round_down(current_net_total)

    # Add field to calculate payment adjustment needed
    payment_adjustment_needed = fields.Monetary(
        string="Payment Adjustment Needed",
        currency_field='transaction_currency',
        compute="_compute_payment_adjustment_needed",
        store=True,
        help="The amount you need to add or reduce from your existing balance to complete payment at the new market price"
    )

    @api.depends('current_net_total', 'net_total', 'payment_amount')
    def _compute_payment_adjustment_needed(self):
        for order in self:
            if order.current_net_total is not None and order.net_total is not None:
                # Calculate the difference between what you should pay at new market price vs old market price
                # Example scenario:
                # - Original market price: 3273, amount to pay: 427.04, paid: 300, balance: 127.04
                # - New market price: 3300, new amount to pay: 430.1
                # - Payment adjustment needed: 430.1 - 427.04 = 3.06 (you need to pay 3.06 more)
                market_price_difference = order.current_net_total - order.net_total
                
                # The payment adjustment needed is the market price difference
                # If positive: you need to pay more (market price increased)
                # If negative: you need to pay less (market price decreased)
                order.payment_adjustment_needed = self.custom_round_down(market_price_difference)
            else:
                order.payment_adjustment_needed = 0.0

    def validate_payment_scenario(self):
        """
        Validates the payment scenario and returns a summary.
        This method helps verify that the payment adjustment calculation is correct.
        """
        self.ensure_one()
        
        if not self.current_market_price or not self.market_price:
            return {
                'valid': False,
                'message': 'No market price change detected. Please set current market price.',
                'details': {}
            }
        
        # Calculate expected values based on your scenario
        original_amount = self.net_total
        current_amount = self.current_net_total
        amount_paid = self.payment_amount
        payment_adjustment = self.payment_adjustment_needed
        final_balance = self.final_balance_after_adjustment
        
        # Validation logic
        expected_final_balance = current_amount - amount_paid
        expected_adjustment = current_amount - original_amount
        
        validation_passed = (
            abs(payment_adjustment - expected_adjustment) < 0.01 and
            abs(final_balance - expected_final_balance) < 0.01
        )
        
        return {
            'valid': validation_passed,
            'message': 'Payment scenario validation passed.' if validation_passed else 'Payment scenario validation failed.',
            'details': {
                'original_amount': original_amount,
                'current_amount': current_amount,
                'amount_paid': amount_paid,
                'payment_adjustment': payment_adjustment,
                'final_balance': final_balance,
                'expected_adjustment': expected_adjustment,
                'expected_final_balance': expected_final_balance,
            }
        }

    # Add field to show final balance after adjustment
    final_balance_after_adjustment = fields.Monetary(
        string="Final Balance After Adjustment",
        currency_field='transaction_currency',
        compute="_compute_final_balance_after_adjustment",
        store=True,
        help="The final amount you need to pay after considering the market price change"
    )

    @api.depends('current_net_payable', 'payment_adjustment_needed')
    def _compute_final_balance_after_adjustment(self):
        for order in self:
            # Final balance is the current net payable (which already considers payments made)
            # The payment_adjustment_needed is already factored into current_net_total
            order.final_balance_after_adjustment = order.current_net_payable

    # Payment-related fields
    selected_payment_ids = fields.Many2many(
        'account.payment',
        string="Vendor Payment",
        domain="[('partner_id', '=', partner_id)]",
        help="Select a payment associated with the vendor."
    )
    payment_amount = fields.Monetary(
        string="Paid Unfixed Amount",
        compute="_compute_payment_amount",
        currency_field='currency_id',
        store=True
    )
    unfixed_balance = fields.Monetary(
        string="Unfixed Balance",
        compute="_compute_unfixed_balance",
        currency_field='currency_id',
        store=True
    )
    current_market_price = fields.Monetary(string="Current Market Price", currency_field='market_price_currency', help="Market price set via the wizard.")
    needs_cost_recalculation = fields.Boolean(string="Needs Cost Recalculation", default=False, help="Indicates if purchase cost chain needs to be recalculated due to market price changes")
    current_net_price = fields.Monetary(
        string="Current Net Market Price",
        compute="_compute_current_net_price",
        currency_field='market_price_currency',
        store=True
    )

    @api.depends('current_market_price', 'discount')
    def _compute_current_net_price(self):
        for order in self:
            if order.current_market_price and order.discount:
                net_price = order.current_market_price + order.discount
                order.current_net_price = self.custom_round_down(net_price)
            else:
                order.current_net_price = self.custom_round_down(order.current_market_price) if order.current_market_price else 0.

    @api.onchange('current_market_price')
    def _onchange_current_market_price(self):
        """Trigger when current market price changes to mark for recalculation"""
        for order in self:
            if order.current_market_price and order.state in ['purchase', 'done']:
                order.needs_cost_recalculation = True

    current_transaction_price_per_unit = fields.Monetary(
        string="Current Transaction Price per Unit",
        currency_field='transaction_currency',
        compute="_compute_current_transaction_price_per_unit",
        store=True
    )

    @api.depends('convention_market_unit', 'current_net_price', 'transaction_currency', 'market_price_currency', 'purchase_method')
    def _compute_current_transaction_price_per_unit(self):
        for order in self:
            if order.convention_market_unit and order.current_net_price and order.transaction_currency:
                converted_market_price = order.market_price_currency._convert(
                    order.current_net_price,
                    order.transaction_currency,
                    order.company_id,
                    order.date_order or fields.Date.today()
                )
                divisor = 31.1034786 if order.purchase_method == 'purchase_2' else 3
                transaction_price_per_unit = converted_market_price / divisor
                order.current_transaction_price_per_unit = self.custom_round_down(transaction_price_per_unit)
            else:
                order.current_transaction_price_per_unit = 0.0

    current_total_subTotal = fields.Monetary(
        string="Current Total Subtotal",
        currency_field='currency_id',
        compute="_compute_current_total_subTotal",
        store=True
    )

    @api.depends('order_line.current_subTotal')
    def _compute_current_total_subTotal(self):
        for order in self:
            order.current_total_subTotal = sum(order.order_line.mapped('current_subTotal'))

    current_profit_loss = fields.Monetary(
        string="Current Profit/Loss",
        currency_field='market_price_currency',
        compute="_compute_current_profit_loss",
        store=True
    )

    @api.depends('current_total_subTotal', 'amount_untaxed')
    def _compute_current_profit_loss(self):
        for order in self:
            if order.current_total_subTotal and order.amount_untaxed:
                order.current_profit_loss = order.current_total_subTotal - order.amount_untaxed
            else:
                order.current_profit_loss = 0.0

    profit_loss = fields.Monetary(
        string="Profit/Loss",
        currency_field='transaction_currency',
        compute="_compute_profit_loss",
        store=True
    )

    @api.depends('current_net_total', 'net_total')
    def _compute_profit_loss(self):
        for order in self:
            if order.current_net_total is not None and order.net_total is not None:
                order.profit_loss = order.current_net_total - order.net_total
            else:
                order.profit_loss = 0.0

    def recalculate_amounts_for_current_market(self):
        """
        Manually trigger recalculation of amounts based on current market price.
        This method can be called to ensure all calculations are up to date.
        """
        for order in self:
            # Force recomputation of all dependent fields
            order._compute_current_net_price()
            order._compute_current_transaction_price_per_unit()
            order._amount_all()
            order._compute_unfixed_balance()
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Recalculation Complete',
                'message': f'Amounts have been recalculated based on current market price for {len(self)} order(s).',
                'type': 'success',
                'sticky': False,
            }
        }

    def recalculate_purchase_cost_chain(self):
        """
        Recalculate purchase cost throughout the entire chain when market price changes.
        This updates purchase_cost in stock moves, MRP productions, and product_cost in sales orders.
        """
        for order in self:
            # Step 1: Update purchase_cost in stock moves for this purchase order
            stock_moves = self.env['stock.move'].search([
                ('purchase_line_id.order_id', '=', order.id),
                ('state', 'in', ['done', 'assigned', 'partially_available'])
            ])
            
            for move in stock_moves:
                # Get the current_subtotal from the purchase line
                purchase_line = move.purchase_line_id
                if purchase_line and purchase_line.current_subTotal:
                    move.purchase_cost = purchase_line.current_subTotal
                    # Trigger recomputation of total_purchase_cost
                    move._compute_total_purchase_cost()
            
            # Step 2: Update stock move lines
            stock_move_lines = self.env['stock.move.line'].search([
                ('move_id', 'in', stock_moves.ids)
            ])
            for line in stock_move_lines:
                line._compute_lot_purchase_cost()
                line._fetch_lot_values()
            
            # Step 3: Update MRP productions that use these stock moves
            mrp_productions = self.env['mrp.production'].search([
                ('move_raw_ids', 'in', stock_moves.ids)
            ])
            for production in mrp_productions:
                production._compute_mrp_purchase_cost()
                # The mo_original_subTotal will be automatically computed via @api.depends
            
            # Step 4: Update stock move lines in MRP productions
            mrp_move_lines = self.env['stock.move.line'].search([
                ('move_id.production_id', 'in', mrp_productions.ids)
            ])
            for line in mrp_move_lines:
                line._fetch_lot_values()
                line._compute_product_quantity()
            
            # Step 5: Force recomputation of all stock move lines that might be affected
            all_affected_move_lines = self.env['stock.move.line'].search([
                ('lot_id', '!=', False)
            ])
            all_affected_move_lines.force_recompute_lot_values()
            all_affected_move_lines.update_mo_purchase_cost_from_lots()
            all_affected_move_lines.force_recompute_original_subtotal()
            
            # Step 5.5: Force recomputation of all MRP productions
            all_mrp_productions = self.env['mrp.production'].search([])
            all_mrp_productions.force_recompute_original_subtotal()
            
            # Step 6: Update sales order lines that reference these stock moves
            sale_order_lines = self.env['sale.order.line'].search([
                ('move_ids', 'in', stock_moves.ids)
            ])
            for line in sale_order_lines:
                line._compute_product_cost()
            
            # Step 7: Update sales orders
            sale_orders = sale_order_lines.mapped('order_id')
            for sale_order in sale_orders:
                sale_order._compute_product_cost()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Purchase Cost Chain Updated',
                'message': f'Purchase cost has been recalculated throughout the chain for {len(self)} order(s).',
                'type': 'success',
                'sticky': False,
            }
        }

    def recalculate_purchase_cost_chain_sql(self):
        """
        Alternative SQL-based method to update purchase cost throughout the chain.
        This method uses direct SQL updates for better performance on large datasets.
        """
        for order in self:
            # Step 1: Update stock.move.purchase_cost
            self.env.cr.execute("""
                UPDATE stock_move sm
                SET purchase_cost = pol.current_subtotal
                FROM purchase_order_line pol
                WHERE sm.purchase_line_id = pol.id
                AND pol.order_id = %s
                AND pol.current_subtotal IS NOT NULL
                AND pol.current_subtotal > 0
            """, (order.id,))
            
            # Step 2: Update stock_move_line.lot_purchase_cost
            self.env.cr.execute("""
                UPDATE stock_move_line sml
                SET lot_purchase_cost = sm.purchase_cost
                FROM stock_move sm
                WHERE sml.move_id = sm.id
                AND sm.purchase_line_id IN (
                    SELECT id FROM purchase_order_line WHERE order_id = %s
                )
            """, (order.id,))
            
            # Step 3: Update stock_move_line.mo_purchase_cost based on lot names
            self.env.cr.execute("""
                UPDATE stock_move_line sml
                SET mo_purchase_cost = (
                    SELECT lot_purchase_cost 
                    FROM stock_move_line sml2 
                    WHERE sml2.lot_id = sml.lot_id 
                    AND sml2.lot_purchase_cost IS NOT NULL 
                    LIMIT 1
                )
                WHERE sml.lot_id IS NOT NULL
                AND sml.move_id IN (
                    SELECT sm.id FROM stock_move sm
                    JOIN purchase_order_line pol ON sm.purchase_line_id = pol.id
                    WHERE pol.order_id = %s
                )
            """, (order.id,))
            
            # Step 4: Update mrp.production.purchase_cost
            self.env.cr.execute("""
                UPDATE mrp_production mp
                SET purchase_cost = (
                    SELECT sm.total_purchase_cost
                    FROM stock_move sm
                    WHERE sm.production_id = mp.id
                    AND sm.total_purchase_cost IS NOT NULL
                    ORDER BY sm.date DESC
                    LIMIT 1
                )
                WHERE mp.id IN (
                    SELECT DISTINCT sm.production_id
                    FROM stock_move sm
                    JOIN purchase_order_line pol ON sm.purchase_line_id = pol.id
                    WHERE pol.order_id = %s
                    AND sm.production_id IS NOT NULL
                )
            """, (order.id,))
            
            # Step 5: Update stock_move_line.product_cost
            self.env.cr.execute("""
                UPDATE stock_move_line sml
                SET product_cost = mp.purchase_cost
                FROM mrp_production mp
                WHERE sml.move_id IN (
                    SELECT id FROM stock_move WHERE production_id = mp.id
                )
                AND mp.purchase_cost IS NOT NULL
                AND mp.id IN (
                    SELECT DISTINCT sm.production_id
                    FROM stock_move sm
                    JOIN purchase_order_line pol ON sm.purchase_line_id = pol.id
                    WHERE pol.order_id = %s
                    AND sm.production_id IS NOT NULL
                )
            """, (order.id,))
            
            # Step 6: Update sale.order.line.product_cost
            self.env.cr.execute("""
                UPDATE sale_order_line sol
                SET product_cost = (
                    SELECT SUM(sml.product_cost)
                    FROM stock_move_line sml
                    JOIN stock_move sm ON sml.move_id = sm.id
                    WHERE sm.sale_line_id = sol.id
                    AND sml.product_cost IS NOT NULL
                )
                WHERE sol.id IN (
                    SELECT DISTINCT sm.sale_line_id
                    FROM stock_move sm
                    JOIN purchase_order_line pol ON sm.purchase_line_id = pol.id
                    WHERE pol.order_id = %s
                    AND sm.sale_line_id IS NOT NULL
                )
            """, (order.id,))
            
            # Step 7: Update sale.order.product_cost
            self.env.cr.execute("""
                UPDATE sale_order so
                SET product_cost = (
                    SELECT AVG(sol.product_cost)
                    FROM sale_order_line sol
                    WHERE sol.order_id = so.id
                    AND sol.product_cost IS NOT NULL
                )
                WHERE so.id IN (
                    SELECT DISTINCT sol.order_id
                    FROM sale_order_line sol
                    JOIN stock_move sm ON sol.id = sm.sale_line_id
                    JOIN purchase_order_line pol ON sm.purchase_line_id = pol.id
                    WHERE pol.order_id = %s
                )
            """, (order.id,))
            
            # Commit the transaction
            self.env.cr.commit()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Purchase Cost Chain Updated (SQL)',
                'message': f'Purchase cost has been recalculated using SQL for {len(self)} order(s).',
                'type': 'success',
                'sticky': False,
            }
        }

    def update_total_first_process_for_existing_orders(self):
        """
        Update total_first_process for existing purchase orders that don't have this value calculated.
        This method is useful for updating old purchase orders after adding the total_first_process field.
        """
        # Find all purchase orders where total_first_process is 0 or NULL
        orders_to_update = self.search([
            '|',
            ('total_first_process', '=', 0),
            ('total_first_process', '=', False)
        ])
        
        updated_count = 0
        for order in orders_to_update:
            # Force recomputation of the totals
            order._compute_totals()
            updated_count += 1
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Total First Process Updated',
                'message': f'Updated total_first_process for {updated_count} purchase order(s).',
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model
    def update_all_total_first_process(self):
        """
        Update total_first_process for all purchase orders in the system.
        This is a model method that can be called from the UI or via a scheduled action.
        """
        all_orders = self.search([])
        updated_count = 0
        
        for order in all_orders:
            # Force recomputation of the totals
            order._compute_totals()
            updated_count += 1
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'All Total First Process Updated',
                'message': f'Updated total_first_process for {updated_count} purchase order(s).',
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model
    def create(self, vals):
        """Override create to handle automatic recalculation"""
        result = super(PurchaseOrder, self).create(vals)
        return result

    def write(self, vals):
        """Override write to handle automatic recalculation"""
        result = super(PurchaseOrder, self).write(vals)
        
        # Check if current_market_price was updated and trigger recalculation
        if 'current_market_price' in vals:
            for order in self:
                if order.state in ['purchase', 'done'] and order.needs_cost_recalculation:
                    # Use a delayed job to avoid blocking the UI
                    order.with_delay().recalculate_purchase_cost_chain()
                    order.needs_cost_recalculation = False
        
        return result

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.onchange('product_id')
    def onchange_product_id(self):
        """Override to prevent automatic product field population"""
        # Do nothing - this prevents automatic field changes when product is selected
        return

    @api.onchange('product_id')
    def onchange_product_id_warning(self):
        """Override to prevent automatic warnings"""
        # Do nothing - this prevents automatic warnings
        return

    gross_weight = fields.Float(string="Gross Weight")
    first_process_wt = fields.Float(string="First Process Wt")
    price = fields.Monetary(string="Market Price")
    second_process_wt = fields.Float(string="Second Process Wt")
    process_loss = fields.Float(string="Process Loss", compute="_compute_process_loss", store=True)
    item_code = fields.Char(string="item code")
    rate = fields.Float(string="Rate", compute="_compute_rate", store=True)
    original_rate = fields.Float(string='Original Rate', compute="_compute_original_rate", store=True)
    qty_g = fields.Float(string="Qty g to t-g", compute="_compute_qty_g", store=True)
    original_qty_g = fields.Float(string="Original Qty", compute="_compute_original_qty_g", store=True)
    uom = fields.Char(string="UOM")
    amount = fields.Monetary(string="Amount", compute="_comput_amount", store=True)
    original_amount = fields.Monetary(string="Amount", compute="_comput_original_amount", store=True)
    transfer_rate = fields.Float(string="Transfer Rate", compute="_compute_transfer_rate", store=True)
    price_currency = fields.Many2one('res.currency', string="Price Currency",
                                     default=lambda self: self.env.ref('base.USD').id)
    dd = fields.Float(string="DD", compute="_compute_dd", digits=(16, 4), store=True)
    actual_dd = fields.Float(string="DD", compute="_compute_actual_dd", store=True)
    manual_dd = fields.Float(string="DD", store=True)
    UGX_currency = fields.Many2one('res.currency', string="Currency", default=lambda self: self.env.ref('base.UGX').id)
    product_quality = fields.Float(string="Product Quality", compute="_compute_product_quality", store=True)
    manual_product_quality = fields.Float(string="Manual Product Quality", compute="_compute_manual_product_quality",
                                          store=True, readonly=False)
    # Computed field to determine if the current company is 'PEX-DRC'
    is_pex_drc = fields.Boolean(compute='_compute_is_pex_drc', store=False)
    @api.depends_context('allowed_company_ids')  # This makes it recompute when company context changes
    def _compute_is_pex_drc(self):
        for record in self:
            current_company_id = self.env.context.get('allowed_company_ids', [self.env.company.id])[0]
            current_company = self.env['res.company'].browse(current_company_id)
            record.is_pex_drc = current_company.name == 'PEX-DRC'

    manual_first_process = fields.Float(
        string="Manual First Process Weight",
        store=True,
        readonly=False,
    )
    original_product_quality = fields.Float(string="Original Product Quality",
                                            compute="_compute_original_product_quality", readonly=True)
    product_quality_difference = fields.Float(string="PQ difference", compute="_compute_product_quality_difference",
                                              readonly=True)
    price_subtotal = fields.Monetary(compute='_compute_amount', string='Subtotal', store=True)
    price_total = fields.Monetary(compute='_compute_amount', string='Total', store=True)
    price_tax = fields.Float(compute='_compute_amount', string='Tax', store=True)
    price_unit = fields.Float(string='Unit Price', required=True, digits='Product Price', compute="_compute_price_unit",
                              readonly=False, store=True)
    product_qty = fields.Float(string='Quantity', required=True, compute='_compute_product_qty', store=True,
                               readonly=False)
    product_uom = fields.Many2one('uom.uom', compute='_compute_product_uom', store=True, readonly=False)
    


    # custom_round_down(2302.842/dd)-219.318

    @api.constrains('first_process_wt', 'second_process_wt')
    def _check_second_process_wt_mandatory(self):
        for record in self:
            if record.first_process_wt > 0 and record.second_process_wt <= 0:
                raise ValidationError(_(
                    " Second Process Wt must be greater than zero."
                ))

    @api.constrains('first_process_wt', 'second_process_wt', 'product_quality')
    def _check_product_quality_range(self):
        for record in self:
            if record.first_process_wt > 0 and record.second_process_wt > 0:
                if not (60 <= record.product_quality <= 100):
                    raise ValidationError(_(
                        "Product Quality must be between 60 and 100."
                    ))

    @api.depends('first_process_wt', 'second_process_wt', 'manual_dd')
    def _compute_dd(self):
        for line in self:
            if line.first_process_wt and line.second_process_wt:
                dd = self.custom_round_down(line.first_process_wt / (line.first_process_wt - line.second_process_wt))
                line.dd = dd
            else:
                line.dd = 0.0

    @api.depends('first_process_wt', 'second_process_wt', )
    def _compute_actual_dd(self):
        for line in self:
            if line.first_process_wt and line.second_process_wt:
                dd = self.custom_round_down(line.first_process_wt / (line.first_process_wt - line.second_process_wt))
                line.actual_dd = dd
            else:
                line.actual_dd = 0.0

    @api.model
    def _prepare_account_move_line(self, move=False):
        """Prepare the values for the creation of account.move.line."""
        res = super(PurchaseOrderLine, self)._prepare_account_move_line(move=move)
        effective_process_wt = self.manual_first_process if self.manual_first_process else self.first_process_wt
        order = self.order_id
        if order.current_market_price and not self.env['ir.config_parameter'].sudo().get_param('purchase_move.disable_current_market_override', False) and not float_is_zero(order.current_market_price, precision_digits=2):
            # Use current market price values for the invoice line
            if effective_process_wt == 0:
                quantity = self.first_process_wt or 1.0
                unrounded_transfer_rate = self.current_price_unit
                subTotal = self.product_qty * unrounded_transfer_rate
            else:
                quantity = effective_process_wt or 1.0
                unrounded_transfer_rate = self.current_subTotal / effective_process_wt if effective_process_wt else 0.0
                subTotal = effective_process_wt * unrounded_transfer_rate
        else:
            if effective_process_wt == 0:
                quantity = self.first_process_wt or 1.0
                unrounded_transfer_rate = self.price_unit
                subTotal = self.product_qty * unrounded_transfer_rate
            else:
                quantity = effective_process_wt or 1.0
                unrounded_transfer_rate = self.price_subtotal / effective_process_wt
                subTotal = effective_process_wt * unrounded_transfer_rate

        res.update({
            'price_unit': unrounded_transfer_rate,
            'subtotal': subTotal,
            'unrounded_transfer_rate': unrounded_transfer_rate,
            'manual_quantity': effective_process_wt,
            'quantity': quantity,
            'price_currency': self.price_currency.id,
            'date_approve': self.date_approve,
        })
        return res

    def custom_round_down(self, value):
        scaled_value = value * 100
        rounded_down_value = math.floor(scaled_value) / 100
        return rounded_down_value

    @api.depends('qty_g', 'product_quality', 'manual_product_quality', 'order_id.transaction_price_per_unit',
                 'order_id.x_factor')
    def _comput_amount(self):
        for line in self:
            # Use manual_product_quality if provided; otherwise, fallback to product_quality
            effective_product_quality = line.manual_product_quality if line.manual_product_quality else line.product_quality

            if line.qty_g and effective_product_quality and line.order_id.transaction_price_per_unit and line.order_id.x_factor:
                try:
                    # Calculate amount and round down the result
                    amount = (
                                     line.qty_g * effective_product_quality * line.order_id.transaction_price_per_unit) / line.order_id.x_factor
                    line.amount = self.custom_round_down(amount)
                except ZeroDivisionError:
                    line.amount = 0.0
            else:
                line.amount = 0.0

    @api.depends('qty_g', 'original_product_quality', 'order_id.transaction_price_per_unit', 'order_id.x_factor')
    def _comput_original_amount(self):
        for line in self:
            if line.qty_g and line.original_product_quality:
                amount = (
                                 line.qty_g * line.original_product_quality * line.order_id.transaction_price_per_unit) / line.order_id.x_factor
                line.original_amount = self.custom_round_down(amount)
            else:
                line.original_amount = 0.0

    formula = fields.Selection(
        related='order_id.formula',  # Accessing the formula of the first order line
        string='Formula',
        readonly=False,  # Ensure it is writable if needed
    )
    date_approve = fields.Datetime(string="Order Deadline", related='order_id.date_approve', readonly=False)

    @api.depends('first_process_wt', 'manual_first_process', 'order_id.material_unit_input',
                 'order_id.transaction_unit')
    def _compute_qty_g(self):
        for line in self:
            # Use manual_first_process if provided; otherwise, fallback to first_process_wt
            effective_process_wt = line.manual_first_process if line.manual_first_process else line.first_process_wt

            if line.order_id.material_unit_input and line.order_id.transaction_unit and effective_process_wt:
                try:
                    unit_input_rate = line.order_id.material_unit_input.ratio
                    transaction_unit_rate = line.order_id.transaction_unit.ratio
                    qty_g = (unit_input_rate / transaction_unit_rate) * effective_process_wt

                    # Round down the computed qty_g
                    line.qty_g = self.custom_round_down(qty_g)
                except ZeroDivisionError:
                    line.qty_g = 0.0
            else:
                line.qty_g = 0.0

    @api.depends('first_process_wt', 'order_id.material_unit_input', 'order_id.transaction_unit')
    def _compute_original_qty_g(self):
        for line in self:
            if line.order_id.material_unit_input and line.order_id.transaction_unit:
                unit_input_rate = line.order_id.material_unit_input.ratio
                transaction_unit_rate = line.order_id.transaction_unit.ratio
                qty_g = (unit_input_rate / transaction_unit_rate) * line.first_process_wt

                line.original_qty_g = self.custom_round_down(qty_g)
            else:
                line.original_qty_g = 0.0

    @api.depends('first_process_wt', 'manual_first_process', 'price_subtotal')
    def _compute_transfer_rate(self):
        for line in self:
            # Use manual_first_process if provided; otherwise, fallback to first_process_wt
            effective_process_wt = line.manual_first_process if line.manual_first_process else line.first_process_wt

            if effective_process_wt and line.price_subtotal:
                try:
                    transfer_rate = line.price_subtotal / effective_process_wt
                    # Assign the computed transfer_rate, rounded down if necessary
                    # line.transfer_rate = self.custom_round_down(transfer_rate)
                    line.transfer_rate = transfer_rate
                except ZeroDivisionError:
                    line.transfer_rate = 0.0
            else:
                line.transfer_rate = 0.0

    @api.depends('manual_dd', 'manual_product_quality')
    def _compute_manual_product_quality(self):
        """Compute manual_product_quality using the formula if manual_dd is provided."""
        for record in self:
            if record.manual_dd:  # If manual_dd is provided, calculate it using the formula
                record.manual_product_quality = self.custom_round_down(
                    abs(self.custom_round_down(
                        (2302.842 / self.custom_round_down(record.manual_dd))
                    ) - 219.318)
                )
            # Else, keep the manual value as is (user-provided)

    @api.model_create_multi
    def _prepare_stock_moves(self, picking):
        res = super(PurchaseOrderLine, self)._prepare_stock_moves(picking)
        for move in res:
            move.update({
                'purchase_cost': self.price_subtotal,
                'product_quality': self.product_quality,
                'first_process_wt': self.first_process_wt,
                'manual_first_process': self.manual_first_process,
                'manual_product_quality': self.manual_product_quality,
                'product_uom_qty': self.first_process_wt,
                'original_subTotal': self.original_subTotal,  # Add original_subTotal
            })
        return res

    @api.depends('manual_product_quality', 'original_product_quality')
    def _compute_product_quality_difference(self):
        for line in self:
            if line.manual_product_quality and line.original_product_quality:
                line.product_quality_difference = line.manual_product_quality - line.original_product_quality
            else:
                line.product_quality_difference = 0.0

    @api.depends('formula', 'first_process_wt', 'second_process_wt', 'gross_weight', 'dd')
    def _compute_product_quality(self):
        for line in self:
            try:
                local_variables = {
                    'first_process_wt': line.first_process_wt,
                    'second_process_wt': line.second_process_wt,
                    'gross_weight': line.gross_weight,
                    'dd': line.dd,
                    'custom_round_down': self.custom_round_down
                }
                formula_dict = dict(line.order_id._compute_formula_selection()).get(line.formula, '')
                #  custom_round_down(2302.842/dd)-219.318
                if formula_dict:
                    result = eval(formula_dict, { }, local_variables)
                    line.product_quality = self.custom_round_down(abs(result))
                else:
                    line.product_quality = 0.0
            except Exception:
                line.product_quality = 0.0

    @api.depends('formula', 'first_process_wt', 'second_process_wt', 'gross_weight')
    def _compute_original_product_quality(self):
        for line in self:
            try:
                local_variables = {
                    'first_process_wt': line.first_process_wt,
                    'second_process_wt': line.second_process_wt,
                    'gross_weight': line.gross_weight,
                    'custom_round_down': self.custom_round_down
                }
                formula_dict = dict(line.order_id._compute_formula_selection()).get(line.formula, '')
                if formula_dict:
                    result = eval(formula_dict, { }, local_variables)
                    line.original_product_quality = self.custom_round_down(abs(result))
                else:
                    line.original_product_quality = 0.0
            except Exception:
                line.original_product_quality = 0.0

    @api.depends('gross_weight', 'first_process_wt')
    def _compute_process_loss(self):
        for record in self:
            if record.gross_weight and record.first_process_wt:
                # Calculate process loss and round down the result
                process_loss = record.gross_weight - record.first_process_wt
                record.process_loss = self.custom_round_down(process_loss)
            else:
                record.process_loss = 0.0

    @api.depends('order_id.transaction_price_per_unit', 'order_id.x_factor', 'product_quality',
                 'manual_product_quality')
    def _compute_rate(self):
        for line in self:
            # Use manual_product_quality if provided; otherwise, fallback to product_quality
            effective_product_quality = line.manual_product_quality if line.manual_product_quality else line.product_quality
            print(f"Effective {effective_product_quality}")
            if line.order_id.transaction_price_per_unit and line.order_id.x_factor and effective_product_quality:
                try:
                    # Calculate rate and round down the result
                    rate = (
                                   line.order_id.transaction_price_per_unit / line.order_id.x_factor) * effective_product_quality
                    line.rate = self.custom_round_down(rate)
                except ZeroDivisionError:
                    line.rate = 0.0
            else:
                line.rate = 0.0

    @api.depends('order_id.transaction_price_per_unit', 'order_id.x_factor', 'original_product_quality')
    def _compute_original_rate(self):
        for line in self:
            if line.order_id.transaction_price_per_unit and line.order_id.x_factor and line.original_product_quality:
                try:
                    # Calculate rate and round down the result
                    rates = (
                                    line.order_id.transaction_price_per_unit / line.order_id.x_factor) * line.original_product_quality
                    line.original_rate = self.custom_round_down(rates)
                except ZeroDivisionError:
                    line.original_rate = 0.0
            else:
                line.original_rate = 0.0

    @api.depends('order_id.material_unit_input')
    def _compute_product_uom(self):
        for line in self:
            if line.order_id.material_unit_input:
                line.product_uom = line.order_id.material_unit_input

    @api.depends('rate', )
    def _compute_price_unit(self):
        for line in self:
            line.price_unit = line.rate

    @api.depends('qty_g', 'product_packaging_qty')
    def _compute_product_qty(self):
        for line in self:
            if line.qty_g:
                line.product_qty = line.qty_g
            else:
                packaging_uom = line.product_packaging_id.product_uom_id
                qty_per_packaging = line.product_packaging_id.qty
                product_qty = packaging_uom._compute_quantity(line.product_packaging_qty * qty_per_packaging,
                                                              line.product_uom)
                if float_compare(product_qty, line.product_qty, precision_rounding=line.product_uom.rounding) != 0:
                    line.product_qty = product_qty

    @api.depends('product_qty', 'price_unit', 'price_currency', 'taxes_id')
    def _compute_amount(self):
        for line in self:
            # Convert price_unit to the base currency if a different currency is selected
            base_currency = self.env.ref('base.USD')  # Replace 'base.USD' with your base currency
            price_unit_in_base = line.price_unit

            if line.price_currency and line.price_currency != base_currency:
                price_unit_in_base = line.price_currency._convert(
                    line.price_unit,
                    base_currency,
                    line.company_id or self.env.company,
                    fields.Date.today()
                )

            # Compute amounts
            subtotal = line.product_qty * price_unit_in_base

            tax_results = self.env['account.tax']._compute_taxes([line._convert_to_tax_base_line_dict()])
            totals = list(tax_results['totals'].values())[0]
            amount_untaxed = line.amount if line.amount else totals['amount_untaxed']
            amount_tax = totals['amount_tax']

            # Update fields
            line.update({
                'price_subtotal': subtotal,
                'price_tax': amount_tax,
                'price_total': subtotal + amount_tax,
            })

    @api.constrains('product_qty', 'price_unit', 'price_subtotal')
    def _check_price_with_quantity(self):
        for line in self:
            if line.product_qty >= 0 and (
                    float_is_zero(line.price_unit, precision_digits=2) or float_is_zero(line.price_subtotal,
                                                                                        precision_digits=2)):
                raise ValidationError(_(
                    "Cannot save purchase order with zero price\n"
                    "Product: %s\n"
                    "Quantity: %s\n"
                    "Price Unit: %s\n"
                    "Subtotal: %s"
                ) % (
                                          line.product_id.display_name,
                                          line.product_qty,
                                          line.price_unit,
                                          line.price_subtotal
                                      ))

    current_rate = fields.Float(string="Current Rate", compute="_compute_current_rate", store=True)
    current_price_unit = fields.Float(string="Current Price Unit", compute="_compute_current_price_unit", store=True)
    current_subTotal = fields.Monetary(string="Current Subtotal", compute="_compute_current_subTotal", store=True, currency_field='price_currency')
    current_amount = fields.Monetary(string="Current Amount", compute="_compute_current_amount", store=True, currency_field='price_currency')
    original_subTotal = fields.Monetary(string="Original Subtotal", compute="_compute_original_subTotal", store=True, currency_field='price_currency')

    @api.depends('qty_g', 'product_quality', 'manual_product_quality', 'order_id.current_transaction_price_per_unit',
                 'order_id.x_factor')
    def _compute_current_amount(self):
        for line in self:
            # Use manual_product_quality if provided; otherwise, fallback to product_quality
            effective_product_quality = line.manual_product_quality if line.manual_product_quality else line.product_quality

            if line.qty_g and effective_product_quality and line.order_id.current_transaction_price_per_unit and line.order_id.x_factor:
                try:
                    # Calculate current amount and round down the result
                    current_amount = (
                        line.qty_g * effective_product_quality * line.order_id.current_transaction_price_per_unit) / line.order_id.x_factor
                    line.current_amount = self.custom_round_down(current_amount)
                except ZeroDivisionError:
                    line.current_amount = 0.0
            else:
                line.current_amount = 0.0

    @api.depends('order_id.current_transaction_price_per_unit', 'order_id.x_factor', 'product_quality', 'manual_product_quality')
    def _compute_current_rate(self):
        for line in self:
            effective_product_quality = line.manual_product_quality if line.manual_product_quality else line.product_quality
            if line.order_id.current_transaction_price_per_unit and line.order_id.x_factor and effective_product_quality:
                try:
                    rate = (
                        line.order_id.current_transaction_price_per_unit / line.order_id.x_factor) * effective_product_quality
                    line.current_rate = self.custom_round_down(rate)
                except ZeroDivisionError:
                    line.current_rate = 0.0
            else:
                line.current_rate = 0.0

    @api.depends('current_rate')
    def _compute_current_price_unit(self):
        for line in self:
            line.current_price_unit = line.current_rate

    @api.depends('current_price_unit', 'product_qty')
    def _compute_current_subTotal(self):
        for line in self:
            line.current_subTotal = line.current_price_unit * line.product_qty

    @api.depends('qty_g', 'product_quality', 'order_id.transaction_price_per_unit', 'order_id.x_factor')
    def _compute_original_subTotal(self):
        for line in self:
            if line.qty_g and line.product_quality and line.order_id.transaction_price_per_unit and line.order_id.x_factor:
                try:
                    # Calculate original subtotal using product_quality (not manual_product_quality)
                    original_rate = self.custom_round_down((line.order_id.transaction_price_per_unit / line.order_id.x_factor) * line.product_quality)
                    line.original_subTotal = self.custom_round_down(original_rate * line.product_qty)
                except ZeroDivisionError:
                    line.original_subTotal = 0.0
            else:
                line.original_subTotal = 0.0


class PurchaseOrderDeductions(models.Model):
    _name = 'purchase.order.deductions'
    _description = 'Deductions in Purchase Orders'

    order_id = fields.Many2one('purchase.order', string='Order Reference', required=True, ondelete='cascade')
    transaction_currency = fields.Many2one('res.currency', string="Transaction Currency",
                                           related='order_id.transaction_currency', store=True)
    account_code = fields.Selection([
        ('deductions', 'Deductions'),
        ('additions', 'Additions'),
    ], string="Account Code", required=True)
    comment = fields.Char(string='Comment')
    currency_id = fields.Many2one('res.currency', string='Currency')
    foreign_currency_amount = fields.Monetary(string='Foreign Currency Amount', currency_field='currency_id')
    transaction_currency_amount = fields.Monetary(string='Transaction Currency Amount',
                                                  currency_field='transaction_currency',
                                                  compute="_compute_transaction_currency_amount")

    @api.depends('foreign_currency_amount', 'transaction_currency', 'account_code')
    def _compute_transaction_currency_amount(self):
        for record in self:
            if record.transaction_currency and record.foreign_currency_amount:
                # Convert the foreign currency amount to the transaction currency
                converted_amount = record.currency_id._convert(
                    record.foreign_currency_amount,
                    record.order_id.transaction_currency,
                    record.order_id.company_id,
                    record.order_id.date_order or fields.Date.today()
                )
                # Adjust based on account code (negative for deductions, positive for additions)
                if record.account_code == 'deductions':
                    record.transaction_currency_amount = -converted_amount
                else:
                    record.transaction_currency_amount = converted_amount
            else:
                record.transaction_currency_amount = 0.0


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    price_unit = fields.Float(string="Price", digits=(16, 4), store=True)
    subtotal = fields.Float(string="Subtotal From Purchase", store=True)
    unrounded_transfer_rate = fields.Float(string="Unrounded Price Unit", store=True)
    manual_quantity = fields.Float(string="Quantity", store=True)
    date_approve = fields.Datetime(string="Order Deadline", readonly=False)
    quantity = fields.Float(
        string='Quantity',
         store=True, readonly=False, precompute=True,
        digits='Product Unit of Measure',
        help="The optional quantity expressed by this line, eg: number of product sold. "
             "The quantity is not a legal requirement but is very useful for some reports.",
    )

    price_total = fields.Monetary(
        string='Total',
        compute='_compute_totals', store=True,
        currency_field='currency_id',
    )
    price_currency = fields.Many2one(
        'res.currency',
        string="Price Currency",

    )

    @api.depends('quantity', 'discount', 'price_unit', 'tax_ids', 'currency_id', 'subtotal', 'unrounded_transfer_rate',
                 'manual_quantity', 'price_currency')
    def _compute_totals(self):
        for line in self:
            if line.display_type != 'product':
                line.price_total = line.price_subtotal = False
                continue

            # Determine the source of the line and compute line_discount_price_unit accordingly
            if line.move_id.is_purchase_document(include_receipts=True):
                effective_quantity = line.manual_quantity if line.manual_quantity else line.quantity
                line_discount_price_unit = line.unrounded_transfer_rate * (1 - (line.discount / 100.0))
            else:
                effective_quantity = line.quantity
                line_discount_price_unit = line.price_unit * (1 - (line.discount / 100.0))

            # Convert price_unit if a price_currency is set and it's different from the base currency
            if line.price_currency and line.currency_id and line.price_currency != line.currency_id:
                converted_price_unit = line.price_currency._convert(
                    line_discount_price_unit,
                    line.currency_id,
                    line.company_id,
                    line.move_id.date or fields.Date.today()
                )
            else:
                converted_price_unit = line_discount_price_unit

            # Calculate the subtotal based on the effective quantity
            subtotal = effective_quantity * converted_price_unit

            # Compute 'price_subtotal' and 'price_total'
            if line.tax_ids:
                taxes_res = line.tax_ids.compute_all(
                    converted_price_unit,
                    quantity=effective_quantity,
                    currency=line.currency_id,
                    product=line.product_id,
                    partner=line.partner_id,
                    is_refund=line.is_refund,
                )
                line.price_subtotal = taxes_res['total_excluded']
                line.price_total = taxes_res['total_included']
            else:
                line.price_total = line.price_subtotal = subtotal