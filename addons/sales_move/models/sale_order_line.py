from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_is_zero, float_compare, float_round
import math

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
    rate = fields.Float(string="Price Unit", compute="_compute_rate", store=True)
    product_cost = fields.Float(string="Product Cost", compute="_compute_product_cost", store=True)
    gross_weight = fields.Float(string="Gross Weight", compute="_compute_gross_weight", store=True)
    net_weight = fields.Float(string="Net Weight", compute="_compute_net_weight", store=True)
    current_rate = fields.Float(string="Current Rate", compute="_compute_current_rate", store=True)
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
    @api.depends('amount_total', 'payment_amount')
    def _compute_unfixed_balance(self):
        for order in self:
            order.unfixed_balance = abs(order.amount_total - order.payment_amount)

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

    @api.depends('order_line.current_rate')
    def _compute_current_rate(self):
        for order in self:
            lines = order.order_line.filtered(lambda line: line.current_rate)
            if lines:
                order.current_rate = sum(lines.mapped('current_rate')) / len(lines)
            else:
                order.current_rate = 0.0

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
                # Update market price to current market price
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
                # Revert market price to old market price
                order.market_price = order.old_market_price

    # def action_open_set_price_wizard(self):
    #     return {
    #         'name': 'Set Current Market Price',
    #         'type': 'ir.actions.act_window',
    #         'res_model': 'set.current.market.price.wizard',
    #         'view_mode': 'form',
    #         'target': 'new',
    #     }
class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"
    rate = fields.Float(string="Rate", compute="_compute_rate", store=True)
    gross_weight = fields.Float(string="Gross Weight", compute="_compute_gross_weight", store=True)
    manual_gross_weight = fields.Float(string="Manual Gross Weight", store=True)
    net_weight = fields.Float(string="Net Weight", compute="_compute_net_weight", store=True)
    inventory_product_quality = fields.Float(string="Inventory Product Quality",compute="_compute_inventory_product_quality", store=True)
    manual_item_quality = fields.Float(string="Manual Item Quality", store=True)
    product_cost = fields.Float(string="Product Cost", compute="_compute_product_cost", store=True)
    current_subTotal = fields.Monetary(string="Current Subtotal", compute="_compute_current_subTotal", store=True)
 
    price_unit = fields.Float(
        string="Unit Price",
        compute='_compute_price_unit',
        digits='Product Price',
        store=True, readonly=False, required=True, precompute=True)

    current_price_unit = fields.Float(
        string="Current Unit Price",
        compute='_compute_current_price_unit',
        digits='Product Price',
        default=0.0,
        store=True, readonly=False, required=True,
    )
    current_rate = fields.Float(string="Current Rate", compute="_compute_current_rate", store=True)

    @api.depends('current_price_unit', 'product_uom_qty')
    def _compute_current_subTotal(self):
        for line in self:
            line.current_subTotal = line.current_price_unit * line.product_uom_qty

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

    @api.depends('order_id.net_price')
    def _compute_rate(self):
        for line in self:
            if line.order_id.net_price:
                line.rate =  self.custom_round_down(line.order_id.net_price/31.1034768)
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
    @api.depends('manual_gross_weight', 'gross_weight', 'manual_item_quality', 'inventory_product_quality')
    def _compute_net_weight(self):
        for line in self:
            quality = line.manual_item_quality if line.manual_item_quality else line.inventory_product_quality
            if line.manual_gross_weight:
                line.net_weight = line.custom_round_down(line.manual_gross_weight * quality / 100)
            else:
                line.net_weight = line.custom_round_down(line.gross_weight * quality / 100)


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


    @api.depends('display_type', 'product_id', 'product_packaging_qty', 'net_weight')
    def _compute_product_uom_qty(self):
        for line in self:
            if line.display_type:
                line.product_uom_qty = 0.0
                continue

            if line.net_weight > 0:
                line.product_uom_qty = line.net_weight
                continue

            if not line.product_packaging_id:
                continue

            packaging_uom = line.product_packaging_id.product_uom_id
            qty_per_packaging = line.product_packaging_id.qty
            product_uom_qty = packaging_uom._compute_quantity(
                line.product_packaging_qty * qty_per_packaging, line.product_uom)

            if float_compare(product_uom_qty, line.product_uom_qty, precision_rounding=line.product_uom.rounding) != 0:
                line.product_uom_qty = product_uom_qty
