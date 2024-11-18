from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round
import math
import logging

_logger = logging.getLogger(__name__)

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'
    currency_id = fields.Many2one('res.currency', string="Currency", invisible=True)
    market_price = fields.Monetary(string="Market Price", currency_field='market_price_currency')
    product_price = fields.Monetary(string="Product Price")
    deduction_head = fields.Float(string="Deduction Head")
    additions = fields.Float(string="Additions")
    market_price_currency = fields.Many2one('res.currency',string="Market Price Currency", default=lambda self: self.env.ref('base.USD').id)
    discount = fields.Float(string="Discount/additions")
    net_price = fields.Monetary(
    string="Net Market Price",
    compute="_compute_net_price",
    currency_field='market_price_currency',
    store=True
    )
    material_unit = fields.Many2one('uom.uom',string="Market Price Unit", default=lambda self: self.env.ref('uom.product_uom_oz').id)
    material_unit_input = fields.Many2one('uom.uom',string="Material Unit Input", default=lambda self: self.env.ref('uom.product_uom_gram').id)
    transaction_currency = fields.Many2one('res.currency', string="Transaction Currency", default=lambda self: self.env.ref('base.USD').id)
    transaction_unit = fields.Many2one('uom.uom',string="Transaction Unit", default=lambda self: self.env.ref('uom.product_uom_ton').id)
    unit_convention = fields.Many2one('uom.uom',string="Unit Convention")
    x_factor = fields.Float(string="Xfactor", default=92)
    net_total = fields.Monetary(string="Net Total", currency_field='transaction_currency', compute="_compute_net_total", store=True)
    deductions = fields.Monetary(string="Deductions",currency_field='transaction_currency', related="total_deductions")
    company_currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True, string="Company Currency"
    )
    transaction_price_per_unit = fields.Monetary(string="Transaction Price per Unit", currency_field='transaction_currency', compute="_compute_transaction_price_per_unit", store=True)
    original_market_price = fields.Monetary(string="Original Market Price", currency_field='company_currency_id')


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


    @api.depends('convention_market_unit', 'net_price', 'transaction_currency', 'market_price_currency')
    def _compute_transaction_price_per_unit(self):
        for order in self:
            if order.convention_market_unit and order.net_price and order.transaction_currency:
                converted_market_price = order.market_price_currency._convert(
                    order.net_price,
                    order.transaction_currency,
                    order.company_id,
                    order.date_order or fields.Date.today()
                )
                # transaction_price_per_unit = order.convention_market_unit * converted_market_price
                transaction_price_per_unit = converted_market_price / 3
                order.transaction_price_per_unit =  self.custom_round_down(transaction_price_per_unit)
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
        method_1 = ICPSudo.get_param('purchase_move.method_1',default='')
        method_2 = ICPSudo.get_param('purchase_move.method_2',default='')
        method_3 = ICPSudo.get_param('purchase_move.method_3',default='')
        return [
            ('method_1', method_1),
            ('method_2', method_2),
            ('method_3', method_3),
        ]
    formula = fields.Selection(
        selection='_compute_formula_selection',
        string='Formula',
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
    amount_untaxed = fields.Monetary(string='Untaxed Amount', store=True, readonly=True, compute='_amount_all', tracking=True)
    tax_totals = fields.Binary(compute='_compute_tax_totals', exportable=False)
    amount_tax = fields.Monetary(string='Taxes', store=True, readonly=True, compute='_amount_all')
    amount_total = fields.Monetary(string='Total', store=True, readonly=True, compute='_amount_all')

    @api.depends('order_line.price_total', 'deductions', 'transaction_currency')
    def _amount_all(self):
        for order in self:
            order_lines = order.order_line.filtered(lambda x: not x.display_type)
            amount_untaxed = sum(order_lines.mapped('amount'))
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

            print(f"Deds {order.deductions}")
            total = (order.amount_untaxed + order.amount_tax) + order.deductions
            order.amount_total = self.custom_round_down(total)



# deductions tab here
    deduction_ids = fields.One2many('purchase.order.deductions', 'order_id', string="Deductions")
    deduction_lines = fields.One2many('purchase.order.deductions', 'order_id', string='Deductions')
    total_deductions = fields.Monetary(string='Total Deductions', currency_field='currency_id', compute="_compute_total_deductions")
    @api.depends('deduction_ids.transaction_currency_amount')
    def _compute_total_deductions(self):
        for order in self:
            total = 0.0
            for deduction in order.deduction_ids:
                total += deduction.transaction_currency_amount
            order.total_deductions = total
# End of deductions tab

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

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

    def custom_round_down(self, value):
        scaled_value = value * 100
        rounded_down_value = math.floor(scaled_value) / 100
        return rounded_down_value

    @api.depends('qty_g', 'product_quality','order_id.transaction_price_per_unit', 'order_id.x_factor')
    def _comput_amount(self):
        for line in self:
            if line.qty_g and line.product_quality:
                amount = (line.qty_g * line.product_quality * line.order_id.transaction_price_per_unit) / line.order_id.x_factor
                line.amount = self.custom_round_down(amount)
            else:
                line.amount = 0.0

    @api.depends('qty_g', 'original_product_quality','order_id.transaction_price_per_unit', 'order_id.x_factor')
    def _comput_original_amount(self):
        for line in self:
            if line.qty_g and line.original_product_quality:
                amount = (line.qty_g * line.original_product_quality * line.order_id.transaction_price_per_unit) / line.order_id.x_factor
                line.original_amount = self.custom_round_down(amount)
            else:
                line.original_amount = 0.0

    formula = fields.Selection(
        related='order_id.formula',  # Accessing the formula of the first order line
        string='Formula',
        readonly=False,  # Ensure it is writable if needed
    )

    @api.depends('first_process_wt', 'order_id.material_unit_input', 'order_id.transaction_unit', 'manual_first_process')
    def _compute_qty_g(self):
        for line in self:
            if line.order_id.material_unit_input and line.order_id.transaction_unit:
                unit_input_rate = line.order_id.material_unit_input.ratio
                transaction_unit_rate = line.order_id.transaction_unit.ratio
                if line.manual_first_process:
                    qty_g = (unit_input_rate / transaction_unit_rate) * line.manual_first_process
                else:
                    qty_g = (unit_input_rate / transaction_unit_rate) * line.first_process_wt

                line.qty_g = self.custom_round_down(qty_g)
            else:
                line.qty_g = 0.0
    @api.depends('first_process_wt', 'order_id.material_unit_input', 'order_id.transaction_unit', 'manual_first_process')
    def _compute_original_qty_g(self):
        for line in self:
            if line.order_id.material_unit_input and line.order_id.transaction_unit:
                unit_input_rate = line.order_id.material_unit_input.ratio
                transaction_unit_rate = line.order_id.transaction_unit.ratio
                qty_g = (unit_input_rate / transaction_unit_rate) * line.first_process_wt

                line.original_qty_g = self.custom_round_down(qty_g)
            else:
                line.original_qty_g = 0.0



    product_quality = fields.Float(string="Product Quality", compute="_compute_product_quality", store=True)
    manual_product_quality = fields.Float(string="Manual PQ", store=True)
    manual_first_process = fields.Float(string="Manua FP", store=True)
    original_product_quality = fields.Float(string="Original Product Quality", compute="_compute_original_product_quality", readonly=True)
    product_quality_difference = fields.Float(string="PQ difference", compute="_compute_product_quality_difference", readonly=True)

    @api.model_create_multi
    def _prepare_stock_moves(self, picking):
        res = super(PurchaseOrderLine, self)._prepare_stock_moves(picking)
        for move in res:
            move.update({
                'product_quality': self.product_quality,
                'first_process_wt': self.first_process_wt,
                'product_uom_qty': self.first_process_wt
            })
        return res

    @api.depends('manual_product_quality', 'original_product_quality')
    def _compute_product_quality_difference(self):
        for line in self:
            if line.manual_product_quality and line.original_product_quality:
                line.product_quality_difference = line.manual_product_quality - line.original_product_quality
            else:
                line.product_quality_difference = 0.0

    @api.depends('formula', 'first_process_wt', 'second_process_wt', 'gross_weight', 'manual_product_quality')
    def _compute_product_quality(self):
        for line in self:
            if line.manual_product_quality:  # Use manually input value if available
                line.product_quality = line.manual_product_quality
            elif line.formula:  # Fallback to computed formula if no manual input
                try:
                    local_variables = {
                        'first_process_wt': line.first_process_wt,
                        'second_process_wt': line.second_process_wt,
                        'gross_weight': line.gross_weight,
                        'custom_round_down': self.custom_round_down
                    }
                    formula_dict = dict(line.order_id._compute_formula_selection()).get(line.formula, '')
                    if formula_dict:
                        result = eval(formula_dict, {}, local_variables)
                        line.product_quality = self.custom_round_down(abs(result))
                    else:
                        line.product_quality = 0.0
                except Exception:
                    line.product_quality = 0.0
            else:
                line.product_quality = 0.0

    @api.depends('formula', 'first_process_wt', 'second_process_wt', 'gross_weight', 'manual_product_quality')
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
                    result = eval(formula_dict, {}, local_variables)
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


    @api.depends('order_id.transaction_price_per_unit', 'order_id.x_factor', 'product_quality')
    def _compute_rate(self):
        for line in self:
            if line.order_id.transaction_price_per_unit and line.order_id.x_factor and line.product_quality:
                try:
                    # Calculate rate and round down the result
                    rate = (line.order_id.transaction_price_per_unit / line.order_id.x_factor) * line.product_quality
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
                    rates = (line.order_id.transaction_price_per_unit / line.order_id.x_factor) * line.original_product_quality
                    line.original_rate = self.custom_round_down(rates)
                except ZeroDivisionError:
                    line.original_rate = 0.0
            else:
                line.original_rate = 0.0


    price_subtotal = fields.Monetary(compute='_compute_amount', string='Subtotal', store=True)
    price_total = fields.Monetary(compute='_compute_amount', string='Total', store=True)
    price_tax = fields.Float(compute='_compute_amount', string='Tax', store=True)
    price_unit = fields.Float(string='Unit Price', required=True, digits='Product Price', compute="_compute_price_unit", readonly=False, store=True)
    product_qty = fields.Float(string='Quantity', required=True, compute='_compute_product_qty', store=True, readonly=False)

    product_uom = fields.Many2one('uom.uom', compute='_compute_product_uom', store=True, readonly=False)

    @api.depends('order_id.material_unit_input')
    def _compute_product_uom(self):
        for line in self:
            if line.order_id.material_unit_input:
                line.product_uom = line.order_id.material_unit_input

    @api.depends('rate',)
    def _compute_price_unit(self):
        for line in self:
            line.price_unit = line.rate

    @api.depends('qty_g')
    def _compute_product_qty(self):
        for line in self:
            line.product_qty = line.qty_g

    @api.depends('product_qty', 'price_unit', 'taxes_id')
    def _compute_amount(self):
        for line in self:
            tax_results = self.env['account.tax']._compute_taxes([line._convert_to_tax_base_line_dict()])
            totals = list(tax_results['totals'].values())[0]
            amount_untaxed = line.amount
            amount_tax = totals['amount_tax']

            line.update({
                'price_subtotal': amount_untaxed,
                'price_tax': amount_tax,
                'price_total': amount_untaxed + amount_tax,
            })


class PurchaseOrderDeductions(models.Model):
    _name = 'purchase.order.deductions'
    _description = 'Deductions in Purchase Orders'

    order_id = fields.Many2one('purchase.order', string='Order Reference', required=True, ondelete='cascade')
    transaction_currency = fields.Many2one('res.currency', string="Transaction Currency", related='order_id.transaction_currency', store=True)
    account_code = fields.Selection([
        ('deductions', 'Deductions'),
        ('additions', 'Additions'),
    ], string="Account Code", required=True)
    comment = fields.Char(string='Comment')
    currency_id = fields.Many2one('res.currency', string='Currency')
    foreign_currency_amount = fields.Monetary(string='Foreign Currency Amount', currency_field='currency_id')
    transaction_currency_amount = fields.Monetary(string='Transaction Currency Amount', currency_field='transaction_currency', compute="_compute_transaction_currency_amount")

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
