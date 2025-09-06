from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero, float_round

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    weighted_average_pq = fields.Float(string="Weighted Average Product Quality", compute='_compute_weighted_average_pq',)
    actual_weighted_pq = fields.Float(string="Actual Weighted Product Quality")
    average_product_quality = fields.Float(string="Product Quality", compute="_compute_product_quality")
    first_process_wt = fields.Float(string="First Process Wt")
    manual_first_process = fields.Float(string="Manual First Process Wt", compute="_compute_manual_first_process", store=True)
    manual_product_quality = fields.Float(string="Manual Product Quality", compute="_compute_manual_product_quality", store=True)
    display_quantity = fields.Float(
        string="Display Quantity",
        compute='_compute_display_quantity',
        store=True,
        readonly=True
    )
    purchase_cost = fields.Float(string="Purchase Cost", compute="_compute_mrp_purchase_cost", store=True)
    original_subTotal = fields.Float(string="Original Subtotal", compute="_compute_mrp_original_subtotal", store=True)
    mo_original_subTotal = fields.Float(string="MO Original Subtotal", compute="_compute_mrp_original_subtotal", store=True)

    @api.depends('move_raw_ids.total_purchase_cost')
    def _compute_mrp_purchase_cost(self):
        for production in self:
            if production.move_raw_ids:
                stock_move = production.move_raw_ids.filtered(lambda m: m.total_purchase_cost).sorted('date', reverse=True)[:1]
                production.purchase_cost = stock_move.total_purchase_cost if stock_move else 0.0
            else:
                production.purchase_cost = 0.0

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

    @api.depends('move_raw_ids.average_lot_manual_first_process')
    def _compute_manual_first_process(self):
        for production in self:
            if production.move_raw_ids:
                stock_move = production.move_raw_ids.filtered(lambda m: m.average_lot_manual_first_process).sorted('date', reverse=True)[:1]
                production.manual_first_process = stock_move.average_lot_manual_first_process if stock_move else 0.0
            else:
                production.manual_first_process = 0.0

    @api.depends('move_raw_ids.average_lot_manual_product_quality')
    def _compute_manual_product_quality(self):
        for production in self:
            if production.move_raw_ids:
                stock_move = production.move_raw_ids.filtered(lambda m: m.average_lot_manual_product_quality).sorted('date', reverse=True)[:1]
                production.manual_product_quality = stock_move.average_lot_manual_product_quality if stock_move else 0.0
            else:
                production.manual_product_quality = 0.0


    @api.depends('move_raw_ids.total_weighted_average')
    def _compute_weighted_average_pq(self):
        for production in self:
            if production.move_raw_ids:
                stock_move = production.move_raw_ids.filtered(lambda m: m.total_weighted_average).sorted('date', reverse=True)[:1]
                production.weighted_average_pq = stock_move.total_weighted_average if stock_move else 0.0
            else:
                production.weighted_average_pq = 0.0

    @api.depends('move_raw_ids.original_subTotal')
    def _compute_mrp_original_subtotal(self):
        for production in self:
            if production.move_raw_ids:
                # Get the total original_subTotal from all raw material moves
                total_original_subtotal = sum(production.move_raw_ids.mapped('original_subTotal'))
                production.mo_original_subTotal = total_original_subtotal
            else:
                production.mo_original_subTotal = 0.0

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

    def _update_raw_moves(self, factor):
        self.ensure_one()
        update_info = []
        moves_to_assign = self.env['stock.move']
        procurements = []

        for move in self.move_raw_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
            old_qty = move.product_uom_qty
            new_qty = float_round(old_qty * factor, precision_rounding=move.product_uom.rounding, rounding_method='UP')
            if new_qty > 0:
                move.write({'product_uom_qty': new_qty})

                # If the product is tracked by lot, respect the existing move lines
                if move.product_id.tracking != 'none':
                    total_qty_done = sum(move.move_line_ids.mapped('qty_done'))
                    total_qty_done_rounded = float_round(total_qty_done, precision_digits=2)
                    new_qty_rounded = float_round(new_qty, precision_digits=2)

                    if total_qty_done_rounded > new_qty_rounded:
                        raise UserError(_("The total quantity of selected lots (%s) exceeds the required quantity (%s).") % (total_qty_done_rounded, new_qty_rounded))
                    elif total_qty_done_rounded < new_qty_rounded:
                        # If the total quantity in move lines is less than the required quantity,
                        # create a new move line for the remaining quantity
                        remaining_qty = new_qty_rounded - total_qty_done_rounded
                        self.env['stock.move.line'].create({
                            'move_id': move.id,
                            'product_id': move.product_id.id,
                            'product_uom_id': move.product_uom.id,
                            'location_id': move.location_id.id,
                            'location_dest_id': move.location_dest_id.id,
                            'qty_done': remaining_qty,
                        })

                if move._should_bypass_reservation() \
                        or move.picking_type_id.reservation_method == 'at_confirm' \
                        or (move.reservation_date and move.reservation_date <= fields.Date.today()):
                    moves_to_assign |= move

                if move.procure_method == 'make_to_order':
                    procurement_qty = new_qty - old_qty
                    values = move._prepare_procurement_values()
                    origin = move._prepare_procurement_origin()
                    procurements.append(self.env['procurement.group'].Procurement(
                        move.product_id, procurement_qty, move.product_uom,
                        move.location_id, move.name, origin, move.company_id, values))

                update_info.append((move, old_qty, new_qty))

        moves_to_assign._action_assign()
        if procurements:
            self.env['procurement.group'].run(procurements)

        return update_info
    
    def force_recompute_original_subtotal(self):
        """
        Force recomputation of mo_original_subTotal for all MRP productions.
        This method specifically updates the mo_original_subTotal from stock moves.
        """
        for production in self:
            if production.move_raw_ids:
                # Get the total original_subTotal from all raw material moves
                total_original_subtotal = sum(production.move_raw_ids.mapped('original_subTotal'))
                production.mo_original_subTotal = total_original_subtotal
            else:
                production.mo_original_subTotal = 0.0

class ChangeProductionQty(models.TransientModel):
    _inherit = 'change.production.qty'

    def change_prod_qty(self):
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        for wizard in self:
            production = wizard.mo_id
            produced = sum(production.move_finished_ids.filtered(lambda m: m.product_id == production.product_id).mapped('quantity_done'))
            if wizard.product_qty < produced:
                format_qty = '%.{precision}f'.format(precision=precision)
                raise UserError(_(
                    "You have already processed %(quantity)s. Please input a quantity higher than %(minimum)s ",
                    quantity=format_qty % produced,
                    minimum=format_qty % produced
                ))
            old_production_qty = production.product_qty
            new_production_qty = wizard.product_qty

            factor = new_production_qty / old_production_qty
            update_info = production._update_raw_moves(factor)
            documents = {}
            for move, old_qty, new_qty in update_info:
                iterate_key = production._get_document_iterate_key(move)
                if iterate_key:
                    document = self.env['stock.picking']._log_activity_get_documents({move: (new_qty, old_qty)}, iterate_key, 'UP')
                    for key, value in document.items():
                        if documents.get(key):
                            documents[key] += [value]
                        else:
                            documents[key] = [value]
            production._log_manufacture_exception(documents)
            self._update_finished_moves(production, new_production_qty, old_production_qty)
            production.write({'product_qty': new_production_qty})
            if not float_is_zero(production.qty_producing, precision_rounding=production.product_uom_id.rounding) and not production.workorder_ids:
                production.qty_producing = new_production_qty
                production._set_qty_producing()

            for wo in production.workorder_ids:
                operation = wo.operation_id
                wo.duration_expected = wo._get_duration_expected(ratio=new_production_qty / old_production_qty)
                quantity = wo.qty_production - wo.qty_produced
                if production.product_id.tracking == 'serial':
                    quantity = 1.0 if not float_is_zero(quantity, precision_digits=precision) else 0.0
                else:
                    quantity = quantity if (quantity > 0 and not float_is_zero(quantity, precision_digits=precision)) else 0
                wo._update_qty_producing(quantity)
                if wo.qty_produced < wo.qty_production and wo.state == 'done':
                    wo.state = 'progress'
                if wo.qty_produced == wo.qty_production and wo.state == 'progress':
                    wo.state = 'done'
                # assign moves; last operation receive all unassigned moves
                moves_raw = production.move_raw_ids.filtered(lambda move: move.operation_id == operation and move.state not in ('done', 'cancel'))
                if wo == production.workorder_ids[-1]:
                    moves_raw |= production.move_raw_ids.filtered(lambda move: not move.operation_id)
                moves_finished = production.move_finished_ids.filtered(lambda move: move.operation_id == operation) #TODO: code does nothing, unless maybe by_products?
                moves_raw.mapped('move_line_ids').write({'workorder_id': wo.id})
                (moves_finished + moves_raw).write({'workorder_id': wo.id})

                # Force reservation update for raw moves
                production.move_raw_ids._action_assign()
                # Ensure availability is recalculated
                production.move_raw_ids._recompute_state()

        # Run scheduler for moves
        self.mo_id.filtered(lambda mo: mo.state in ['confirmed', 'progress']).move_raw_ids._trigger_scheduler()

        return {}