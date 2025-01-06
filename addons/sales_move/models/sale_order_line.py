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
    current_market_price = fields.Monetary(string="Current Market Price", currency_field='market_price_currency')
    profit_loss = fields.Monetary(string="Profit/Loss", compute="_compute_profit_loss", currency_field='market_price_currency')
    discount = fields.Float(string="Discount/additions", default=-23)
    net_price = fields.Monetary(
    string="Net Price",
    compute="_compute_net_price",
    currency_field='market_price_currency',
    store=True
    )

    def custom_round_down(self, value):
        scaled_value = value * 100
        rounded_down_value = math.floor(scaled_value) / 100
        return rounded_down_value

    def _compute_profit_loss(self):
        for order in self:
            if order.market_price and order.current_market_price:
                order.profit_loss = order.current_market_price - order.market_price
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

    # def action_confirm(self):
    #     """Override confirm method to change state to 'unfixed'."""
    #     for order in self:
    #         if order.state not in ('unfixed', 'sale'):
    #             order.state = 'unfixed'
    #         else:
    #             super(SaleOrder, self).action_confirm()

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

    def action_open_set_price_wizard(self):
        return {
            'name': 'Set Current Market Price',
            'type': 'ir.actions.act_window',
            'res_model': 'set.current.market.price.wizard',
            'view_mode': 'form',
            'target': 'new',
        }
class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"
    rate = fields.Float(string="Rate", compute="_compute_rate", store=True)
    gross_weight = fields.Float(string="Gross Weight", compute="_compute_gross_weight", store=True)
    manual_gross_weight = fields.Float(string="Manual Gross Weight", store=True)
    net_weight = fields.Float(string="Net Weight", compute="_compute_net_weight", store=True)
    inventory_product_quality = fields.Float(string="Inventory Product Quality",compute="_compute_inventory_product_quality", store=True)
    manual_item_quality = fields.Float(string="Manual Item Quality", store=True)
    product_cost = fields.Float(string="Product Cost", compute="_compute_product_cost", store=True)
    price_unit = fields.Float(
        string="Unit Price",
        compute='_compute_price_unit',
        digits='Product Price',
        store=True, readonly=False, required=True, precompute=True)
    
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
