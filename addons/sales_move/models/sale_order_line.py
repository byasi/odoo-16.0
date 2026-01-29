from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_is_zero, float_compare, float_round
import math
from datetime import date

READONLY_FIELD_STATES = {
    state: [('readonly', True)]
    for state in {'cancel'}
}

class SaleOrder(models.Model):
    _inherit = 'sale.order'


    state = fields.Selection(
        selection_add=[('unfixed', 'Unfixed')],  # Add new state
        ondelete={'unfixed': 'set default'}
    )
    market_price_currency = fields.Many2one('res.currency',string="Market Price Currency", default=lambda self: self.env.ref('base.USD').id)
    market_price = fields.Monetary(string="Market Price", currency_field='market_price_currency')
    old_market_price = fields.Monetary(string="Old Market Price", currency_field='market_price_currency')
    current_market_price = fields.Monetary(string="Current Market Price", currency_field='market_price_currency', help="Market price set via the wizard.")
    profit_loss = fields.Monetary(string="Profit/Loss", compute="_compute_profit_loss", currency_field='market_price_currency')
    original_profit = fields.Monetary(string="Original Profit", compute="_compute_original_profit_loss", currency_field='market_price_currency')
    discount = fields.Float(string="Discount/additions", default=-23)
    net_price = fields.Monetary(
    string="Net Price",
    compute="_compute_net_price",
    currency_field='market_price_currency',
    store=True
    )
    current_net_price = fields.Monetary(
    string="Net Price",
    compute="_compute_current_net_price",
    currency_field='market_price_currency',
    store=True
    )

    total_current_subTotal = fields.Monetary(
        string="Total Current Subtotal",
        currency_field='currency_id',
        compute="_compute_total_current_subTotal",
        store=True,
    )
    product_quality = fields.Float(
        string="Product Quality",
        compute="_compute_product_quality",
        store=True
    )
    rate = fields.Float(string="Price Unit", compute="_compute_rate", digits=(16, 5), store=True)
    product_cost = fields.Float(string="Product Cost", compute="_compute_product_cost", store=True)
    gross_weight = fields.Float(string="Gross Weight", compute="_compute_gross_weight", store=True)
    net_weight = fields.Float(string="Net Weight", compute="_compute_net_weight", store=True)
    current_rate = fields.Float(string="Current Rate", digits=(16, 5), compute="_compute_current_rate", store=True)
    current_exchange_rate = fields.Float(
        string="Current Exchange Rate",
        digits=(16, 6),
        compute="_compute_current_exchange_rate",
        inverse="_inverse_current_exchange_rate",
        store=True,
        readonly=False,
        help="Manual rate when unfixed: 1 unit of 'Rate From Currency' = this many units of 'Rate To Currency'. On fix, Odoo rates are used."
    )
    current_exchange_rate_currency_from = fields.Many2one(
        'res.currency',
        string="Rate From Currency",
        default=lambda self: self.env.ref('base.USD', raise_if_not_found=False),
        help="Currency for the manual exchange rate (1 unit of this = Current Exchange Rate units of Rate To Currency). Only used when order is unfixed."
    )
    current_exchange_rate_currency_to = fields.Many2one(
        'res.currency',
        string="Rate To Currency",
        default=lambda self: self.env.ref('base.UGX', raise_if_not_found=False),
        help="Currency for the manual exchange rate. Only used when order is unfixed."
    )
    selected_payment_ids = fields.Many2many(
        'account.payment',
        string="Customer Payment",
        domain="[('partner_id', '=', partner_id)]",
        help="Select a payment associated with the customer."
    )
    payment_amount = fields.Monetary(
        string="Paid Unfixed Amount",
        compute="_compute_payment_amount",
        currency_field='currency_id',
        store=True
    )
    unfixed_balance = fields.Monetary(
        string="Paid Unfixed Amount",
        compute="_compute_unfixed_balance",
        currency_field='currency_id',
        store=True
    )
    date_order = fields.Datetime(
        string="Order Date",
        required=True, readonly=False,
        states=READONLY_FIELD_STATES,
        help="Creation date of draft/sent orders,\nConfirmation date of confirmed orders.",
        default=fields.Datetime.now)

    is_date_order_past = fields.Boolean(
        compute="_compute_is_date_order_past", store=True
    )

    amount_total = fields.Monetary(string="Total", store=True, compute='_compute_amounts', tracking=4)

    # Sales 2
    sales_method = fields.Selection(
        selection=[
            ('sales_1', 'Sales 1'),
            ('sales_2', 'Sales 2'),
        ],
        string="Sales Method",  
        default='sales_1',
        required=True,
    )
    market_price_unit = fields.Many2one('uom.uom', string="Market Price Unit",
                                        default=lambda self: self.env.ref('uom.product_uom_oz').id)
    market_price_unit_input = fields.Many2one('uom.uom', string="Market Price Unit Input",
                                          default=lambda self: self.env.ref('uom.product_uom_gram').id)
    x_factor = fields.Float(string="Xfactor",default=100, store=True)
    transaction_price_per_unit = fields.Monetary(string="Transaction Price Per Unit", currency_field='market_price_currency', compute='_compute_transaction_price_per_unit', store=True)
    transaction_unit = fields.Many2one('uom.uom', string="Transaction Unit",
                                     default=lambda self: self.env.ref('uom.product_uom_ton').id,
                                     store=True)
    convention_market_unit = fields.Float(
        string="Conversion Market Unit",
        compute="_compute_convention_market_unit",
        store=True
    )
    
    @api.depends('order_line.price_subtotal', 'order_line.price_tax', 'order_line.price_total')
    def _compute_amounts(self):
        """
        Compute the total amounts of the SO, including untaxed amount, tax amount, and total amount.
        This method uses the price_subtotal, price_tax, and price_total fields from the order lines,
        which are computed based on manual_quantity if provided.
        """
        for order in self:
            order = order.with_company(order.company_id)
            # Filter out non-product lines (e.g., section or note lines)
            order_lines = order.order_line.filtered(lambda x: not x.display_type)

            if order.company_id.tax_calculation_rounding_method == 'round_globally':
                # Compute taxes globally for all order lines
                tax_results = order.env['account.tax']._compute_taxes([
                    line._convert_to_tax_base_line_dict()
                    for line in order_lines
                ])
                totals = tax_results['totals']
                amount_untaxed = totals.get(order.currency_id, {}).get('amount_untaxed', 0.0)
                amount_tax = totals.get(order.currency_id, {}).get('amount_tax', 0.0)
            else:
                # Compute taxes line by line and sum the results
                amount_untaxed = sum(order_lines.mapped('price_subtotal'))
                amount_tax = sum(order_lines.mapped('price_tax'))

            # Update the order amounts
            order.update({
                'amount_untaxed': amount_untaxed,
                'amount_tax': amount_tax,
                'amount_total': amount_untaxed + amount_tax,
            })

    @api.depends('date_order')
    def _compute_is_date_order_past(self):
        for order in self:
            order.is_date_order_past = order.date_order and order.date_order.date() < fields.Date.today()
            print(f"OrderPast: {order.is_date_order_past}")


    @api.depends('amount_total', 'payment_amount')
    def _compute_unfixed_balance(self):
        for order in self:
            order.unfixed_balance = abs(order.amount_total - order.payment_amount)

    @api.depends('selected_payment_ids', 'state', 'current_exchange_rate', 'current_exchange_rate_currency_from', 'current_exchange_rate_currency_to')
    def _compute_payment_amount(self):
        for record in self:
            total_amount = 0.0
            conv_date = fields.Date.context_today(record)
            for payment in record.selected_payment_ids:
                if payment.currency_id != record.currency_id:
                    # When unfixed, use manual exchange rate if the pair matches; else Odoo rate
                    rate = record._get_conversion_rate_for_order(
                        payment.currency_id,
                        record.currency_id,
                        payment.date or conv_date
                    )
                    total_amount += payment.amount * rate
                else:
                    total_amount += payment.amount
            record.payment_amount = total_amount

    @api.depends('order_line.current_rate')
    def _compute_current_rate(self):
        for order in self:
            lines = order.order_line.filtered(lambda line: line.current_rate)
            if lines:
                order.current_rate = sum(lines.mapped('current_rate')) / len(lines)
            else:
                order.current_rate = 0.0

    @api.depends('currency_id', 'market_price_currency', 'current_exchange_rate_currency_from', 'current_exchange_rate_currency_to', 'date_order')
    def _compute_current_exchange_rate(self):
        for order in self:
            from_cur = order.current_exchange_rate_currency_from or order.currency_id
            to_cur = order.current_exchange_rate_currency_to or order.market_price_currency
            if from_cur and to_cur and from_cur != to_cur:
                try:
                    conversion_date = order.date_order.date() if order.date_order else fields.Date.today()
                    order.current_exchange_rate = self.env['res.currency']._get_conversion_rate(
                        from_cur,
                        to_cur,
                        order.company_id,
                        conversion_date
                    )
                except Exception:
                    order.current_exchange_rate = 0.0
            else:
                order.current_exchange_rate = 1.0

    def _inverse_current_exchange_rate(self):
        pass

    @api.onchange('currency_id', 'market_price_currency', 'state')
    def _onchange_currency_set_rate_currencies(self):
        """Default manual rate currency pair from order and market price currency when unfixed."""
        if self.state == 'unfixed':
            if not self.current_exchange_rate_currency_from and self.currency_id:
                self.current_exchange_rate_currency_from = self.currency_id
            if not self.current_exchange_rate_currency_to and self.market_price_currency:
                self.current_exchange_rate_currency_to = self.market_price_currency

    def _get_conversion_rate_for_order(self, from_currency, to_currency, conversion_date=None):
        """
        Return the conversion rate from from_currency to to_currency.
        When order is unfixed and manual rate currencies match, use current_exchange_rate (manual).
        When fixed (or no manual rate), use Odoo's rate so profit/loss is accurate.
        """
        self.ensure_one()
        if not from_currency or not to_currency or from_currency == to_currency:
            return 1.0
        date = conversion_date or (self.date_order.date() if self.date_order else fields.Date.today())
        from_cur = self.current_exchange_rate_currency_from or self.currency_id
        to_cur = self.current_exchange_rate_currency_to or self.market_price_currency
        # Use manual rate only when unfixed and we have a manual rate and the pair matches
        if (
            self.state == 'unfixed'
            and self.current_exchange_rate
            and from_cur and to_cur
        ):
            if from_currency == from_cur and to_currency == to_cur:
                return self.current_exchange_rate
            if from_currency == to_cur and to_currency == from_cur:
                return 1.0 / self.current_exchange_rate if self.current_exchange_rate else 0.0
        return self.env['res.currency']._get_conversion_rate(
            from_currency, to_currency, self.company_id, date
        )

    @api.depends('order_line.net_weight')
    def _compute_net_weight(self):
        for order in self:
            lines = order.order_line.filtered(lambda line: line.net_weight)
            if lines:
                order.net_weight = sum(lines.mapped('net_weight')) / len(lines)
            else:
                order.net_weight = 0.0

    @api.depends('order_line.gross_weight')
    def _compute_gross_weight(self):
        for order in self:
            lines = order.order_line.filtered(lambda line: line.gross_weight)
            if lines:
                order.gross_weight = sum(lines.mapped('gross_weight')) / len(lines)
            else:
                order.gross_weight = 0.0

    @api.depends('order_line.product_cost')
    def _compute_product_cost(self):
        for order in self:
            lines = order.order_line.filtered(lambda line: line.product_cost)
            if lines:
                order.product_cost = sum(lines.mapped('product_cost')) / len(lines)
            else:
                order.product_cost = 0.0

    @api.depends('order_line.rate')
    def _compute_rate(self):
        for order in self:
            lines = order.order_line.filtered(lambda line: line.rate)
            if lines:
                order.rate = sum(lines.mapped('rate')) / len(lines)
            else:
                order.rate = 0.0


    @api.depends('order_line.inventory_product_quality')
    def _compute_product_quality(self):
        for order in self:
            lines = order.order_line.filtered(lambda line: line.inventory_product_quality)
            if lines:
                order.product_quality = sum(lines.mapped('inventory_product_quality')) / len(lines)
            else:
                order.product_quality = 0.0


    @api.depends('order_line.current_subTotal')
    def _compute_total_current_subTotal(self):
        for order in self:
            order.total_current_subTotal = sum(order.order_line.mapped('current_subTotal'))

    @api.depends('amount_total', 'order_line.product_cost', 'order_line.current_subTotal')
    def _compute_original_profit_loss(self):
        for order in self:
            total_product_cost = sum(order.order_line.mapped('product_cost'))
            if total_product_cost and order.total_current_subTotal:
                order.original_profit = order.total_current_subTotal - total_product_cost
            elif total_product_cost and order.amount_total:
                order.original_profit = order.amount_total - total_product_cost
            else:
                order.original_profit = 0.0

    @api.depends('current_market_price', 'discount')
    def _compute_current_net_price(self):
        for order in self:
            if order.current_market_price and order.discount:
                net_price = order.current_market_price + order.discount
                order.current_net_price = self.custom_round_down(net_price)
            else:
                order.current_net_price = self.custom_round_down(order.current_market_price) if order.current_market_price else 0.

    def custom_round_down(self, value):
        scaled_value = value * 100
        rounded_down_value = math.floor(scaled_value) / 100
        return rounded_down_value

    @api.depends('total_current_subTotal', 'amount_untaxed')
    def _compute_profit_loss(self):
        for order in self:
            if order.total_current_subTotal and order.amount_untaxed:
                order.profit_loss = order.total_current_subTotal - order.amount_untaxed
            else:
                order.profit_loss = 0.0

    @api.depends('market_price', 'discount')
    def _compute_net_price(self):
        for order in self:
            if order.market_price and order.discount:
                net_price = order.market_price + order.discount
                order.net_price = self.custom_round_down(net_price)
            else:
                order.net_price = self.custom_round_down(order.market_price) if order.market_price else 0.

    @api.depends('convention_market_unit', 'net_price', 'market_price_currency', 'sales_method')
    def _compute_transaction_price_per_unit(self):
        for order in self:
            if order.convention_market_unit and order.net_price and order.market_price_currency:
                # Use different divisor based on sales method
                divisor = 3 if order.sales_method == 'sales_2' else 3
                transaction_price_per_unit = order.net_price / divisor
                order.transaction_price_per_unit = self.custom_round_down(transaction_price_per_unit)
            else:
                order.transaction_price_per_unit = 0.0

    @api.depends('market_price_unit', 'transaction_unit')
    def _compute_convention_market_unit(self):
        for record in self:
            if record.market_price_unit and record.transaction_unit:
                record.convention_market_unit = self.custom_round_down(
                    record.transaction_unit._compute_quantity(1, record.market_price_unit)
                )
            else:
                record.convention_market_unit = 0.0


    def action_convert_to_sales_order(self):
        """ Confirm the given quotation(s) and set their confirmation date.

        If the corresponding setting is enabled, also locks the Sale Order.

        :return: True
        :rtype: bool
        :raise: UserError if trying to confirm locked or cancelled SO's
        """
        if self._get_forbidden_state_confirm() & set(self.mapped('state')):
            raise UserError(_(
                "It is not allowed to confirm an order in the following states: %s",
                ", ".join(self._get_forbidden_state_confirm()),
            ))

        self.order_line._validate_analytic_distribution()

        for order in self:
            order.validate_taxes_on_sales_order()
            if order.state == 'unfixed':
                order.state = 'sale'
                # Move current market price to old market price
                order.old_market_price = order.market_price
                # Update market price to current market price only if it's not zero
                if not float_is_zero(order.current_market_price, precision_digits=2):
                    order.market_price = order.current_market_price
            if order.partner_id in order.message_partner_ids:
                continue
            order.message_subscribe([order.partner_id.id])

        self.write(self._prepare_confirmation_values())

        # Context key 'default_name' is sometimes propagated up to here.
        # We don't need it and it creates issues in the creation of linked records.
        context = self._context.copy()
        context.pop('default_name', None)

        self.with_context(context)._action_confirm()

        if self[:1].create_uid.has_group('sale.group_auto_done_setting'):
            # Public user can confirm SO, so we check the group on any record creator.
            self.action_done()

        return True
    def action_back_to_unpicked(self):
        """Convert 'Sales Order' back to 'unfixed'."""
        for order in self:
            if order.state == 'sale':
                order.state = 'unfixed'
                # Revert market price to old market price only if old_market_price is not zero
                if not float_is_zero(order.old_market_price, precision_digits=2):
                    order.market_price = order.old_market_price

class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"
    rate = fields.Float(string="Rate", compute="_compute_rate", digits=(16, 5), store=True)
    gross_weight = fields.Float(string="Gross Weight", compute="_compute_gross_weight", store=True)
    manual_gross_weight = fields.Float(string="Manual Gross Weight", store=True)
    net_weight = fields.Float(string="Net Weight", compute="_compute_net_weight", store=True)
    inventory_product_quality = fields.Float(string="Inventory Product Quality",compute="_compute_inventory_product_quality", store=True)
    manual_item_quality = fields.Float(string="Manual Item Quality", store=True)
    manual_product_quality = fields.Float(string="Manual Product Quality", store=True)
    product_cost = fields.Float(string="Product Cost", compute="_compute_product_cost", store=True)
    current_subTotal = fields.Monetary(string="Current Subtotal", compute="_compute_current_subTotal", store=True)
    manual_quantity = fields.Float(string="Manual Quantity", store=True)
    unfixed_balance = fields.Monetary(
        string="Unfixed Balance",
        compute="_compute_unfixed_balance",
        currency_field='currency_id',
        store=True
    )
    qty = fields.Float(string="Qty", compute="_compute_qty_g", store=True)
    first_process_wt = fields.Float(string="First Process Wt", compute="_compute_first_process_wt", store=True)

    price_unit = fields.Float(
        string="Unit Price",
        compute='_compute_price_unit',
        # digits='Product Price',
        digits=(16, 5),
        store=True, readonly=False, required=True, precompute=True)

    current_price_unit = fields.Float(
        string="Current Unit Price",
        compute='_compute_current_price_unit',
        digits='Product Price',
        default=0.0,
        store=True, readonly=False, required=True,
    )
    current_rate = fields.Float(string="Current Rate", compute="_compute_current_rate", store=True)
    price_subtotal = fields.Monetary(
        string="Subtotal",
        compute='_compute_amount',
        store=True, precompute=True)

    @api.depends('gross_weight')
    def _compute_first_process_wt(self):
        for line in self:
            line.first_process_wt = line.gross_weight if line.gross_weight else 0.0

   
    @api.depends('first_process_wt', 'order_id.transaction_unit', 'order_id.market_price_unit_input')
    def _compute_qty_g(self):
        for line in self:
          if line.order_id.transaction_unit and line.order_id.market_price_unit_input:
            unit_input_rate = line.order_id.market_price_unit_input.ratio
            transaction_unit_rate = line.order_id.transaction_unit.ratio
            qty_g = (unit_input_rate / transaction_unit_rate) * line.first_process_wt
            line.qty = self.custom_round_down(qty_g)
          else:
            line.qty = 0.0

    @api.depends('product_uom_qty', 'discount', 'price_unit', 'tax_id', 'manual_quantity')
    def _compute_amount(self):
        """
        Compute the amounts of the SO line, using manual_quantity if provided.
        """
        for line in self:
            # Use manual_quantity if it is provided (greater than 0), otherwise use product_uom_qty
            quantity = line.manual_quantity if line.manual_quantity > 0 else line.product_uom_qty

            # Prepare the tax base line dictionary with the updated quantity
            tax_base_line_dict = line._convert_to_tax_base_line_dict()
            tax_base_line_dict['quantity'] = quantity  # Override quantity with manual_quantity

            # Compute taxes using the updated quantity
            tax_results = self.env['account.tax'].with_company(line.company_id)._compute_taxes([tax_base_line_dict])
            totals = list(tax_results['totals'].values())[0]
            amount_untaxed = totals['amount_untaxed']
            amount_tax = totals['amount_tax']

            # Update the line with the new amounts
            line.update({
                'price_subtotal': amount_untaxed,
                'price_tax': amount_tax,
                'price_total': amount_untaxed + amount_tax,
            })


    @api.depends('current_price_unit', 'manual_quantity', 'product_uom_qty')
    def _compute_current_subTotal(self):
        """
        Compute the subtotal based on manual_quantity if provided, otherwise use product_uom_qty.
        """
        for line in self:
            # Use manual_quantity if it is set (greater than 0), otherwise use product_uom_qty
            quantity = line.manual_quantity if line.manual_quantity > 0 else line.product_uom_qty
            line.current_subTotal = line.current_price_unit * quantity

    @api.depends('order_id.current_net_price')
    def _compute_current_rate(self):
        for line in self:
            if line.order_id.current_net_price:
                line.current_rate =  self.custom_round_down(line.order_id.current_net_price/31.1034768)
            else:
                line.current_rate = 0.0

    @api.depends('current_rate')
    def _compute_current_price_unit(self):
        for line in self:
            line.current_price_unit = line.current_rate


    @api.depends('rate')
    def _compute_price_unit(self):
        for line in self:
            line.price_unit = line.rate


    def custom_round_down(self, value):
        scaled_value = value * 100
        rounded_down_value = math.floor(scaled_value) / 100
        return rounded_down_value


    product_uom_qty = fields.Float(
        string="Quantity",
        compute='_compute_product_uom_qty',
        digits='Product Unit of Measure', default=1.0,
        store=True, readonly=False, required=True, precompute=True)

    @api.depends('order_id.sales_method', 'order_id.net_price', 'order_id.transaction_price_per_unit', 
                 'order_id.x_factor', 'inventory_product_quality', 'manual_product_quality')
    def _compute_rate(self):
        for line in self:
            if line.order_id.sales_method == 'sales_2':
                # Sales 2 method: use xfactor and new fields
                if line.order_id.transaction_price_per_unit and line.order_id.x_factor:
                    # Use manual_product_quality if available, otherwise fall back to inventory_product_quality
                    quality = line.manual_product_quality if line.manual_product_quality else line.inventory_product_quality
                    if quality:
                        rate = (line.order_id.transaction_price_per_unit / line.order_id.x_factor) * quality
                        # line.rate = self.custom_round_down(rate)
                        line.rate = rate
                    else:
                        line.rate = 0.0
                else:
                    line.rate = 0.0
            else:
                # Sales 1 method: use default calculation (net_price/31.1034768)
                if line.order_id.net_price:
                    rate = line.order_id.net_price / 31.1034768
                    # line.rate = self.custom_round_down(rate)
                    line.rate = rate
                else:
                    line.rate = 0.0

    @api.depends('qty_delivered')
    def _compute_gross_weight(self):
        for line in self:
            if line.qty_delivered > 0:
                line.gross_weight = line.qty_delivered
            else:
                line.gross_weight = 0.0

    # gross×quality/100
    @api.depends('manual_gross_weight', 'gross_weight', 'manual_product_quality', 'inventory_product_quality', 'order_id.sales_method', 'qty')
    def _compute_net_weight(self):
        for line in self:
            # For sales_2 method, set both manual_quantity and product_uom_qty to qty
            if line.order_id.sales_method == 'sales_2':
                line.manual_quantity = line.qty
                # Only update product_uom_qty on editable SO states to avoid creating new pickings
                if line.order_id.state in ('draft', 'sent', 'unfixed'):
                    line.product_uom_qty = line.qty
                # Still compute net_weight for other purposes
                quality = line.manual_product_quality if line.manual_product_quality else line.inventory_product_quality
                if line.manual_gross_weight:
                    line.net_weight = line.manual_gross_weight * quality / 100
                else:
                    line.net_weight = line.gross_weight * quality / 100
            else:
                # Original logic for sales_1
                quality = line.manual_product_quality if line.manual_product_quality else line.inventory_product_quality
                if line.manual_gross_weight:
                    line.net_weight = line.manual_gross_weight * quality / 100
                else:
                    line.net_weight = line.gross_weight * quality / 100

                # Update manual_quantity instead of directly changing quantity
                line.manual_quantity = line.net_weight

    @api.depends('qty_delivered', 'product_id')
    def _compute_inventory_product_quality(self):
        for line in self:
            if line.qty_delivered > 0 and line.product_id:
                # Find the related stock.moves for this sale.order.line
                stock_moves = self.env['stock.move'].search([
                    ('sale_line_id', '=', line.id),
                    ('product_id', '=', line.product_id.id),
                    ('state', '=', 'done')  # Only consider completed moves
                ])

                if stock_moves:
                    # Fetch all stock.move.lines related to these stock.moves
                    stock_move_lines = self.env['stock.move.line'].search([
                        ('move_id', 'in', stock_moves.ids)
                    ])

                    # Calculate the average value of average_product_quality
                    if stock_move_lines:
                        total_quality = sum(stock_move_lines.mapped('average_product_quality'))
                        line.inventory_product_quality = total_quality / len(stock_move_lines)
                    else:
                        line.inventory_product_quality = 0.0
                else:
                    line.inventory_product_quality = 0.0
            else:
                line.inventory_product_quality = 0.0

    @api.depends('qty_delivered', 'product_id')
    def _compute_product_cost(self):
        for line in self:
            if line.qty_delivered > 0 and line.product_id:
                # Find the related stock.moves for this sale.order.line
                stock_moves = self.env['stock.move'].search([
                    ('sale_line_id', '=', line.id),
                    ('product_id', '=', line.product_id.id),
                    ('state', '=', 'done')  # Only consider completed moves
                ])

                if stock_moves:
                    # Fetch all stock.move.lines related to these stock.moves
                    stock_move_lines = self.env['stock.move.line'].search([
                        ('move_id', 'in', stock_moves.ids)
                    ])

                    # Calculate the average value of average_product_quality
                    if stock_move_lines:
                        total_cost = sum(stock_move_lines.mapped('product_cost'))
                        line.product_cost = total_cost
                    else:
                        line.product_cost = 0.0
                else:
                    line.product_cost = 0.0
            else:
                line.product_cost = 0.0


    @api.depends('display_type', 'product_id', 'product_packaging_qty', 'gross_weight',  'inventory_product_quality', 'order_id.sales_method', 'qty')
    def _compute_product_uom_qty(self):
        for line in self:

            if line.display_type:
                line.product_uom_qty = 0.0
                continue

            # For sales_2 method, set product_uom_qty to qty
            if line.order_id.sales_method == 'sales_2':
                # Only update in editable SO states to avoid spawning new WH/OUT transfers
                if line.order_id.state in ('draft', 'sent', 'unfixed'):
                    line.product_uom_qty = line.qty
                # Whether updated or not, skip the remaining default logic for sales_1
                continue

            if line.manual_gross_weight:
                line.product_uom_qty = line.gross_weight * line.inventory_product_quality / 100
                continue

            if not line.product_packaging_id:
                continue

            packaging_uom = line.product_packaging_id.product_uom_id
            qty_per_packaging = line.product_packaging_id.qty
            product_uom_qty = packaging_uom._compute_quantity(
                line.product_packaging_qty * qty_per_packaging, line.product_uom)

            if float_compare(product_uom_qty, line.product_uom_qty, precision_rounding=line.product_uom.rounding) != 0:
                line.product_uom_qty = product_uom_qty

    @api.depends('order_id.unfixed_balance', 'price_subtotal', 'order_id.amount_total')
    def _compute_unfixed_balance(self):
        for line in self:
            if line.order_id.amount_total:
                # Calculate the proportion of the line's subtotal to the total order amount
                proportion = line.price_subtotal / line.order_id.amount_total
                # Apply the same proportion to the unfixed balance
                line.unfixed_balance = line.order_id.unfixed_balance * proportion
            else:
                line.unfixed_balance = 0.0

    def _prepare_invoice_line(self, **optional_values):
        """
        Prepare the dict of values to create the new invoice line for a sales order line.
        """
        res = super(SaleOrderLine, self)._prepare_invoice_line(**optional_values)
        res.update({
            'manual_quantity_so': self.manual_quantity,
            'unfixed_balance': self.unfixed_balance,
            'product_cost': self.product_cost,  # Pass product_cost from sale order line to invoice line
        })
        return res

class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    manual_quantity_so = fields.Float(string="Manual Quantity", store=True)
    unfixed_balance = fields.Monetary(
        string="Unfixed Balance",
        currency_field='currency_id',
        store=True
    )
    price_total = fields.Monetary(
        string='Total',
        compute='_compute_totals', store=True,
        currency_field='currency_id',
    )

    @api.depends('quantity', 'discount', 'price_unit', 'tax_ids', 'currency_id', 'subtotal', 'unrounded_transfer_rate',
                 'manual_quantity_so', 'price_currency')
    def _compute_totals(self):
        for line in self:
            if line.display_type != 'product':
                line.price_total = line.price_subtotal = False
                continue

            # Use manual_quantity_so if it is set, otherwise use quantity
            effective_quantity = line.manual_quantity_so if line.manual_quantity_so else line.quantity

            # Compute the price unit after discount
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