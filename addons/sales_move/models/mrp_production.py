from odoo import models, fields, api, _

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    weighted_average_pq = fields.Float(string="Weighted Average Product Quality", compute='_compute_weighted_average_pq',)
    actual_weighted_pq = fields.Float(string="Actual Weighted Product Quality")
    average_product_quality = fields.Float(string="Product Quality", compute="_compute_product_quality")
    first_process_wt = fields.Float(string="First Process Wt")
    display_quantity = fields.Float(
        string="Display Quantity",
        compute='_compute_display_quantity',
        store=True,
        readonly=True
    )

    @api.depends('move_raw_ids.display_quantity')
    def _compute_display_quantity(self):
        for production in self:
            if production.move_raw_ids:
                stock_move = production.move_raw_ids.filtered(lambda m: m.display_quantity).sorted('date', reverse=True)[:1]
                production.display_quantity = stock_move.display_quantity if stock_move else 0.0
            else:
                production.display_quantity = 0.0

    @api.depends('move_raw_ids.average_lot_product_quality')
    def _compute_product_quality(self):
        for production in self:
            if production.move_raw_ids:
                stock_move = production.move_raw_ids.filtered(lambda m: m.average_lot_product_quality).sorted('date', reverse=True)[:1]
                production.average_product_quality = stock_move.average_lot_product_quality if stock_move else 0.0
            else:
                production.average_product_quality = 0.0


    @api.depends('move_raw_ids.total_weighted_average')
    def _compute_weighted_average_pq(self):
        for production in self:
            if production.move_raw_ids:
                stock_move = production.move_raw_ids.filtered(lambda m: m.total_weighted_average).sorted('date', reverse=True)[:1]
                production.weighted_average_pq = stock_move.total_weighted_average if stock_move else 0.0
            else:
                production.weighted_average_pq = 0.0

    def button_mark_done(self):
        self._button_mark_done_sanity_checks()
        self = self.with_context(skip_fetch_lot_values=True)

        if not self.env.context.get('button_mark_done_production_ids'):
            self = self.with_context(button_mark_done_production_ids=self.ids)
        res = self._pre_button_mark_done()
        if res is not True:
            return res

        if self.env.context.get('mo_ids_to_backorder'):
            productions_to_backorder = self.browse(self.env.context['mo_ids_to_backorder'])
            productions_not_to_backorder = self - productions_to_backorder
        else:
            productions_not_to_backorder = self
            productions_to_backorder = self.env['mrp.production']

        self.workorder_ids.button_finish()

        backorders = productions_to_backorder and productions_to_backorder._split_productions()
        backorders = backorders - productions_to_backorder

        productions_not_to_backorder._post_inventory(cancel_backorder=True)
        productions_to_backorder._post_inventory(cancel_backorder=True)

        # if completed products make other confirmed/partially_available moves available, assign them
        done_move_finished_ids = (productions_to_backorder.move_finished_ids | productions_not_to_backorder.move_finished_ids).filtered(lambda m: m.state == 'done')
        done_move_finished_ids._trigger_assign()

        # Moves without quantity done are not posted => set them as done instead of canceling. In
        # case the user edits the MO later on and sets some consumed quantity on those, we do not
        # want the move lines to be canceled.
        (productions_not_to_backorder.move_raw_ids | productions_not_to_backorder.move_finished_ids).filtered(lambda x: x.state not in ('done', 'cancel')).write({
            'state': 'done',
            'product_uom_qty': 0.0,
        })
        for production in self:
            production.write({
                'date_finished': fields.Datetime.now(),
                'product_qty': production.qty_produced,
                'priority': '0',
                'is_locked': True,
                'state': 'done',
            })

        if not backorders:
            if self.env.context.get('from_workorder'):
                return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'mrp.production',
                    'views': [[self.env.ref('mrp.mrp_production_form_view').id, 'form']],
                    'res_id': self.id,
                    'target': 'main',
                }
            if self.user_has_groups('mrp.group_mrp_reception_report') and self.picking_type_id.auto_show_reception_report:
                lines = self.move_finished_ids.filtered(lambda m: m.product_id.type == 'product' and m.state != 'cancel' and m.quantity_done and not m.move_dest_ids)
                if lines:
                    if any(mo.show_allocation for mo in self):
                        action = self.action_view_reception_report()
                        return action
            return True
        context = self.env.context.copy()
        context = {k: v for k, v in context.items() if not k.startswith('default_')}
        for k, v in context.items():
            if k.startswith('skip_'):
                context[k] = False
        action = {
            'res_model': 'mrp.production',
            'type': 'ir.actions.act_window',
            'context': dict(context, mo_ids_to_backorder=None, button_mark_done_production_ids=None)
        }
        if len(backorders) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': backorders[0].id,
            })
        else:
            action.update({
                'name': _("Backorder MO"),
                'domain': [('id', 'in', backorders.ids)],
                'view_mode': 'tree,form',
            })
        return action
class ChangeProductionQty(models.TransientModel):
    _inherit = 'change.production.qty'

    # product_qty = fields.Float(
    #         'Quantity To Produce',
    #         compute='_compute_product_qty',
    #         digits='Product Unit of Measure',store=True)

    # # overrides the
    # @api.depends_context('active_id')
    # def _compute_product_qty(self):
    #     # Access the production order using the active_id from the context
    #     for record in self:
    #         production_id = self.env.context.get('active_id')
    #         if production_id:
    #             production = self.env['mrp.production'].browse(production_id)
    #             record.product_qty = production.display_quantity
    #         else:
    #             record.product_qty = 0.0