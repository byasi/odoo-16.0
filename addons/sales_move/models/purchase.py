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
    currency = fields.Many2one('res.currency', string="Currency", default=lambda self: self.env.ref('base.UGX').id)
    partner_street = fields.Char(related='partner_id.street', string="Street", readonly=True)
    partner_city = fields.Char(related='partner_id.city', string="City", readonly=True)
    partner_zip = fields.Char(related='partner_id.zip', string="ZIP", readonly=True)
    partner_country = fields.Many2one(related='partner_id.country_id', string="Country", readonly=True)
    partner_contact = fields.Char(related='partner_id.phone', string="Contact", readonly=True)
    

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
    amount_untaxed = fields.Monetary(string='Untaxed Amount', store=True, readonly=True, compute='_amount_all', tracking=True)
    tax_totals = fields.Binary(compute='_compute_tax_totals', exportable=False)
    amount_tax = fields.Monetary(string='Taxes', store=True, readonly=True, compute='_amount_all')
    amount_total = fields.Monetary(string='Total', store=True, readonly=True, compute='_amount_all')

    @api.depends('order_line.price_total', 'deductions', 'transaction_currency')
    def _amount_all(self):
        for order in self:
            order_lines = order.order_line.filtered(lambda x: not x.display_type)
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
    transfer_rate = fields.Float(string="Transfer Rate", compute="_compute_transfer_rate", store=True)
    price_currency = fields.Many2one('res.currency',string="Price Currency", default=lambda self: self.env.ref('base.USD').id)
    dd = fields.Float(string="DD", compute="_compute_dd",digits=(16, 4), store=True)
    actual_dd = fields.Float(string="DD", compute="_compute_actual_dd", store=True)
    manual_dd = fields.Float(string="DD", store=True)
    UGX_currency = fields.Many2one('res.currency', string="Currency", default=lambda self: self.env.ref('base.UGX').id)
    # custom_round_down(2302.842/dd)-219.318

    @api.depends('first_process_wt', 'second_process_wt', 'manual_dd')
    def _compute_dd(self):
        for line in self:
            if line.first_process_wt and line.second_process_wt:
                dd = self.custom_round_down(line.first_process_wt / (line.first_process_wt - line.second_process_wt))
                line.dd = dd
            else:
                line.dd = 0.0

    @api.depends('first_process_wt', 'second_process_wt',)
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
        if effective_process_wt == 0:
            unrounded_transfer_rate = self.price_unit
            subTotal =  self.product_qty * unrounded_transfer_rate
        else :
            unrounded_transfer_rate = self.price_subtotal / effective_process_wt
            subTotal =  effective_process_wt * unrounded_transfer_rate

        # Update price_unit to match transfer_rate
        res.update({
            'price_unit': unrounded_transfer_rate,
            'subtotal': subTotal,
            'unrounded_transfer_rate': unrounded_transfer_rate,
            'manual_quantity': self.manual_first_process,
            'price_currency': self.price_currency.id,
        })
        return res

    def custom_round_down(self, value):
        scaled_value = value * 100
        rounded_down_value = math.floor(scaled_value) / 100
        return rounded_down_value

    @api.depends('qty_g', 'product_quality', 'manual_product_quality', 'order_id.transaction_price_per_unit', 'order_id.x_factor')
    def _comput_amount(self):
        for line in self:
            # Use manual_product_quality if provided; otherwise, fallback to product_quality
            effective_product_quality = line.manual_product_quality if line.manual_product_quality else line.product_quality

            if line.qty_g and effective_product_quality and line.order_id.transaction_price_per_unit and line.order_id.x_factor:
                try:
                    # Calculate amount and round down the result
                    amount = (line.qty_g * effective_product_quality * line.order_id.transaction_price_per_unit) / line.order_id.x_factor
                    line.amount = self.custom_round_down(amount)
                except ZeroDivisionError:
                    line.amount = 0.0
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

    @api.depends('first_process_wt', 'manual_first_process', 'order_id.material_unit_input', 'order_id.transaction_unit')
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


    product_quality = fields.Float(string="Product Quality", compute="_compute_product_quality", store=True)
    manual_product_quality = fields.Float(string="Manual Product Quality", compute="_compute_manual_product_quality", store=True, readonly=False)
    manual_first_process = fields.Float(string="Manual First Process Weight", store=True)
    original_product_quality = fields.Float(string="Original Product Quality", compute="_compute_original_product_quality", readonly=True)
    product_quality_difference = fields.Float(string="PQ difference", compute="_compute_product_quality_difference", readonly=True)

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
                'product_uom_qty': self.first_process_wt,
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
                    if formula_dict:
                        result = eval(formula_dict, {}, local_variables)
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


    @api.depends('order_id.transaction_price_per_unit', 'order_id.x_factor', 'product_quality', 'manual_product_quality')
    def _compute_rate(self):
        for line in self:
            # Use manual_product_quality if provided; otherwise, fallback to product_quality
            effective_product_quality = line.manual_product_quality if line.manual_product_quality else line.product_quality
            print(f"Effective {effective_product_quality}")
            if line.order_id.transaction_price_per_unit and line.order_id.x_factor and effective_product_quality:
                try:
                    # Calculate rate and round down the result
                    rate = (line.order_id.transaction_price_per_unit / line.order_id.x_factor) * effective_product_quality
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

    @api.depends('qty_g', 'product_packaging_qty')
    def _compute_product_qty(self):
        for line in self:
            if line.qty_g:
                line.product_qty = line.qty_g
            else:
                packaging_uom = line.product_packaging_id.product_uom_id
                qty_per_packaging = line.product_packaging_id.qty
                product_qty = packaging_uom._compute_quantity(line.product_packaging_qty * qty_per_packaging, line.product_uom)
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

class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    price_unit = fields.Float(string="Price", digits=(16, 4), store=True)
    subtotal = fields.Float(string="Subtotal From Purchase", store=True)
    unrounded_transfer_rate = fields.Float(string="Unrounded Price Unit", store=True)
    manual_quantity = fields.Float(string="Quantity", store=True)
    price_total = fields.Monetary(
        string='Total',
        compute='_compute_totals', store=True,
        currency_field='currency_id',
    )
    price_currency = fields.Many2one(
        'res.currency',
        string="Price Currency",

    )

    @api.depends('quantity', 'discount', 'price_unit', 'tax_ids', 'currency_id', 'subtotal', 'unrounded_transfer_rate', 'manual_quantity', 'price_currency')
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
