# -*- coding: utf-8 -*-
from datetime import date, datetime, time
from odoo import api, fields, models


class PurchaseOrderAnalysisLine(models.TransientModel):
    _name = 'purchase.order.analysis.line'
    _description = 'Purchase Order Analysis Line'

    wizard_id = fields.Many2one('purchase.order.analysis.wizard', ondelete='cascade')
    order_id = fields.Many2one('purchase.order', string='Order', required=True, ondelete='cascade')
    selected = fields.Boolean(string='Include', default=True)
    # Display fields from order
    partner_id = fields.Many2one(related='order_id.partner_id', string='Vendor', readonly=True)
    date_order = fields.Datetime(related='order_id.date_order', string='Order Date', readonly=True)
    state = fields.Selection(related='order_id.state', string='Status', readonly=True)
    net_price = fields.Monetary(
        related='order_id.net_price',
        string='Net Price',
        readonly=True,
        currency_field='currency_id',
    )
    product_quality = fields.Float(related='order_id.product_quality', string='Product Quality', readonly=True)
    manual_weighted_product_quality = fields.Float(
        related='order_id.manual_weighted_product_quality',
        string='Manual Wtd. PQ',
        readonly=True,
    )
    total_first_process = fields.Float(related='order_id.total_first_process', string='Total First Process', readonly=True)
    total_with_weights = fields.Float(related='order_id.total_with_weights', string='Total RM', readonly=True)
    currency_id = fields.Many2one(related='order_id.company_id.currency_id', string='Currency', readonly=True)
    order_currency_id = fields.Many2one(related='order_id.currency_id', string='Order Currency', readonly=True)
    total_original_subtotal = fields.Monetary(
        related='order_id.total_original_subtotal',
        string='Original Subtotal',
        readonly=True,
        currency_field='order_currency_id',
    )
    total_effective_subtotal = fields.Monetary(
        related='order_id.total_effective_subtotal',
        string='Effective Subtotal',
        readonly=True,
        currency_field='order_currency_id',
    )
    manual_pq_profit_loss = fields.Monetary(
        string='Profit / Loss',
        compute='_compute_manual_pq_profit_loss',
        readonly=True,
        currency_field='order_currency_id',
    )

    @api.depends(
        'order_id',
        'order_id.total_original_subtotal',
        'order_id.total_effective_subtotal',
    )
    def _compute_manual_pq_profit_loss(self):
        """Do not use related= to PO field: it forces a read of a group-restricted field for all users."""
        has_pl = self.env.user.has_group('sales_move.group_profit_access')
        for line in self:
            if has_pl and line.order_id:
                line.manual_pq_profit_loss = line.order_id.manual_pq_profit_loss
            else:
                line.manual_pq_profit_loss = 0.0


class PurchaseOrderAnalysisWizard(models.TransientModel):
    _name = 'purchase.order.analysis.wizard'
    _description = 'Purchase Order Analysis by Date Range'

    date_from = fields.Date(
        string='Start Date',
        required=True,
        default=lambda self: date.today().replace(day=1),
    )
    date_to = fields.Date(
        string='End Date',
        required=True,
        default=lambda self: fields.Date.context_today(self),
    )
    order_line_ids = fields.One2many(
        'purchase.order.analysis.line',
        'wizard_id',
        string='Purchase Orders',
        readonly=False,
    )
    has_orders = fields.Boolean(compute='_compute_has_orders', string='Has Orders')
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)

    @api.depends('order_line_ids')
    def _compute_has_orders(self):
        for w in self:
            w.has_orders = bool(w.order_line_ids)
    average_net_price = fields.Monetary(
        string='Average Net Price',
        compute='_compute_averages',
        currency_field='currency_id',
        readonly=True,
    )
    average_weighted_product_quality = fields.Float(
        string='Average Weighted Product Quality',
        compute='_compute_averages',
        readonly=True,
        digits=(16, 2),
    )
    total_first_process_wt = fields.Float(
        string='Total First Process (Weight)',
        compute='_compute_averages',
        readonly=True,
        digits=(16, 2),
    )
    average_weighted_manual_product_quality = fields.Float(
        string='Average Weighted Manual Product Quality',
        compute='_compute_averages',
        readonly=True,
        digits=(16, 2),
    )
    total_original_subtotal_sum = fields.Monetary(
        string='Sum Original Subtotal',
        compute='_compute_averages',
        currency_field='currency_id',
        readonly=True,
    )
    total_effective_subtotal_sum = fields.Monetary(
        string='Sum Effective Subtotal',
        compute='_compute_averages',
        currency_field='currency_id',
        readonly=True,
    )
    total_manual_pq_profit_loss_sum = fields.Monetary(
        string='Sum Profit / Loss',
        compute='_compute_averages',
        currency_field='currency_id',
        readonly=True,
    )
    selected_count = fields.Integer(
        string='Selected Orders',
        compute='_compute_averages',
        readonly=True,
    )

    @api.depends(
        'order_line_ids', 'order_line_ids.selected', 'order_line_ids.order_id.net_price',
        'order_line_ids.order_id.product_quality', 'order_line_ids.order_id.total_first_process',
        'order_line_ids.order_id.manual_weighted_product_quality',
        'order_line_ids.order_id.total_manual_process_weight',
        'order_line_ids.order_id.total_original_subtotal', 'order_line_ids.order_id.total_effective_subtotal',
    )
    def _compute_averages(self):
        for wizard in self:
            selected_lines = wizard.order_line_ids.filtered(lambda l: l.selected and l.order_id)
            if not selected_lines:
                wizard.average_net_price = 0.0
                wizard.average_weighted_product_quality = 0.0
                wizard.average_weighted_manual_product_quality = 0.0
                wizard.total_first_process_wt = 0.0
                wizard.total_original_subtotal_sum = 0.0
                wizard.total_effective_subtotal_sum = 0.0
                wizard.total_manual_pq_profit_loss_sum = 0.0
                wizard.selected_count = 0
                if wizard.order_line_ids and wizard.order_line_ids[0].order_currency_id:
                    wizard.currency_id = wizard.order_line_ids[0].order_currency_id
                continue
            # Average net price (simple average)
            total_net = sum(l.net_price for l in selected_lines)
            wizard.average_net_price = total_net / len(selected_lines)
            wizard.selected_count = len(selected_lines)
            # Weighted average product quality: sum(pq * weight) / sum(weight)
            total_weight = sum(l.total_first_process for l in selected_lines)
            wizard.total_first_process_wt = round(total_weight, 2)
            if total_weight:
                weighted_sum = sum(
                    l.order_id.product_quality * l.order_id.total_first_process
                    for l in selected_lines
                )
                wizard.average_weighted_product_quality = round(weighted_sum / total_weight, 2)
            else:
                wizard.average_weighted_product_quality = 0.0
            # Manual weighted PQ across orders (weight = total_manual_process_weight per order)
            tw_m = sum(
                l.order_id.total_manual_process_weight for l in selected_lines
                if l.order_id.total_manual_process_weight
            )
            if tw_m:
                w_manual = sum(
                    l.order_id.manual_weighted_product_quality * l.order_id.total_manual_process_weight
                    for l in selected_lines if l.order_id.total_manual_process_weight
                )
                wizard.average_weighted_manual_product_quality = round(w_manual / tw_m, 2)
            else:
                wizard.average_weighted_manual_product_quality = 0.0
            wizard.total_original_subtotal_sum = sum(l.order_id.total_original_subtotal for l in selected_lines)
            wizard.total_effective_subtotal_sum = sum(l.order_id.total_effective_subtotal for l in selected_lines)
            # Sum line P/L (lines never read PO.manual_pq_profit_loss for users without Profit Access)
            wizard.total_manual_pq_profit_loss_sum = sum(l.manual_pq_profit_loss for l in selected_lines)
            if selected_lines and selected_lines[0].order_currency_id:
                wizard.currency_id = selected_lines[0].order_currency_id

    def action_load_orders(self):
        self.ensure_one()
        self.order_line_ids.unlink()
        dt_from = datetime.combine(self.date_from, time.min)
        dt_to = datetime.combine(self.date_to, time.max)
        domain = [
            ('date_order', '>=', dt_from),
            ('date_order', '<=', dt_to),
            # Include RFQs (draft), sent, unfixed, purchase, etc.; only exclude cancelled
            ('state', '!=', 'cancel'),
        ]
        orders = self.env['purchase.order'].search(domain, order='date_order desc')
        lines = self.env['purchase.order.analysis.line'].create([
            {
                'wizard_id': self.id,
                'order_id': order.id,
                'selected': True,
            }
            for order in orders
        ])
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
