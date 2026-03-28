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
    total_first_process = fields.Float(related='order_id.total_first_process', string='Total First Process', readonly=True)
    total_with_weights = fields.Float(related='order_id.total_with_weights', string='Total RM', readonly=True)
    currency_id = fields.Many2one(related='order_id.company_id.currency_id', string='Currency', readonly=True)


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
    selected_count = fields.Integer(
        string='Selected Orders',
        compute='_compute_averages',
        readonly=True,
    )

    @api.depends('order_line_ids', 'order_line_ids.selected', 'order_line_ids.order_id.net_price',
                 'order_line_ids.order_id.product_quality', 'order_line_ids.order_id.total_first_process')
    def _compute_averages(self):
        for wizard in self:
            selected_lines = wizard.order_line_ids.filtered(lambda l: l.selected and l.order_id)
            if not selected_lines:
                wizard.average_net_price = 0.0
                wizard.average_weighted_product_quality = 0.0
                wizard.total_first_process_wt = 0.0
                wizard.selected_count = 0
                if wizard.order_line_ids and wizard.order_line_ids[0].currency_id:
                    wizard.currency_id = wizard.order_line_ids[0].currency_id
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
            if selected_lines and selected_lines[0].currency_id:
                wizard.currency_id = selected_lines[0].currency_id

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
