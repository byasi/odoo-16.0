from odoo import _, models, fields, api
from odoo.exceptions import UserError, ValidationError
import math

from odoo.tools import float_compare, float_is_zero
from odoo.tools.misc import OrderedSet

class StockMove(models.Model):
    _inherit = 'stock.move'
    
    def _get_price_unit(self):
        """
        Override to use product_cost from stock.move.line when available for outgoing moves.
        This ensures the stock delivery accounting entry uses the actual cost from manufacturing orders.
        
        The cost is calculated from move lines: sum(product_cost from all move lines) / quantity_done
        This matches the calculation used in the invoice COGS to ensure reconciliation.
        """
        # First check if this is an outgoing move with custom cost from move lines
        if (self._is_out() 
            and self.quantity_done > 0
            and self.move_line_ids):
            
            # Get total cost from all move lines (product_cost comes from manufacturing order)
            total_cost_from_lines = sum(self.move_line_ids.mapped('product_cost'))
            
            if total_cost_from_lines and not float_is_zero(total_cost_from_lines, precision_rounding=self.product_id.uom_id.rounding):
                # Get quantity done in product UOM (the actual quantity delivered)
                quantity_done_in_product_uom = self.product_uom._compute_quantity(
                    self.quantity_done, self.product_id.uom_id
                )
                
                if not float_is_zero(quantity_done_in_product_uom, precision_rounding=self.product_id.uom_id.rounding):
                    # Calculate cost per unit: total_cost_from_lines / quantity_done
                    # This gives us the cost per unit in product UOM
                    cost_per_unit_product_uom = total_cost_from_lines / quantity_done_in_product_uom
                    
                    # Convert to move's UOM for return
                    cost_per_unit_move_uom = self.product_id.uom_id._compute_price(
                        cost_per_unit_product_uom, self.product_uom
                    )
                    
                    return cost_per_unit_move_uom
        
        # Fall back to default calculation
        return super(StockMove, self)._get_price_unit()
    def custom_round_down(self, value):
        scaled_value = value * 100
        rounded_down_value = math.floor(scaled_value) / 100
        return rounded_down_value

    product_quality = fields.Float(string="Product Quality", store=True)
    actual_weighted_pq = fields.Float(string="Actual Weighted Product Quality")
    first_process_wt = fields.Float(string="First Process Wt", store=True)
    manual_first_process = fields.Float(string="Manual First Process Wt", store=True)
    manual_product_quality = fields.Float(string="Manual Product Quality", store=True)
    total_weighted_average = fields.Float(
    string="Total Weighted Average Quality",
    compute="_compute_total_weighted_average",
    store=True,
    readonly=True
    )
    total_weighted_average_manual = fields.Float(
    string="Total Weighted Average Quality Manual",
    compute="_compute_total_weighted_average_manual",
    store=True,
    readonly=True
    )
    purchase_cost = fields.Float(string="Purchase Cost", store=True, readonly=True)
    net_price = fields.Float(string="Net Price", store=True, readonly=True)
    total_net_price = fields.Float(string="Total Net Price", compute="_compute_total_net_price", store=True, readonly=True)
    display_quantity = fields.Float(
    string="Product Quantity",
    compute="_compute_display_quantity",
    digits=(16, 4),
    store=True,
    readonly=True)

    average_lot_product_quality = fields.Float(
        string="Average Lot Product Quality",
        compute="_compute_average_values",
        store=True,
        readonly=True
    )
    average_lot_first_process_wt = fields.Float(
        string="Average Lot First Process Wt",
        compute="_compute_average_values",
        store=True,
        readonly=True
    )
    average_lot_manual_first_process = fields.Float(
        string="Average Lot Manual First Process Wt",
        compute="_compute_average_values",
        store=True,
        readonly=True
    )
    average_lot_manual_product_quality = fields.Float(
        string="Average Lot Manual Product Quality",
        compute="_compute_average_values",
        store=True,
        readonly=True
    )
    total_purchase_cost = fields.Float(string="Purchase Cost", compute="_compute_total_purchase_cost", store=True, readonly=True)
    original_subTotal = fields.Float(string="Original Subtotal", store=True)
    total_original_subTotal = fields.Float(string="Total Original Subtotal", compute="_compute_original_subtotal", store=True)
    @api.depends('move_line_ids.mo_product_quality', 'move_line_ids.mo_first_process_wt', 'move_line_ids.mo_manual_first_process', 'move_line_ids.mo_manual_product_quality')
    def _compute_average_values(self):
        for move in self:
            total_lines = len(move.move_line_ids)
            total_product_quality = self.custom_round_down(sum(line.mo_product_quality for line in move.move_line_ids))

            total_first_process_wt = self.custom_round_down(sum(line.mo_first_process_wt for line in move.move_line_ids))
            total_manual_first_process = self.custom_round_down(sum(line.mo_manual_first_process for line in move.move_line_ids))
            total_manual_product_quality = self.custom_round_down(sum(line.mo_manual_product_quality for line in move.move_line_ids))

            move.average_lot_product_quality = self.custom_round_down((total_product_quality / total_lines)) if total_lines else 0.0
            move.average_lot_first_process_wt = self.custom_round_down((total_first_process_wt / total_lines)) if total_lines else 0.0
            move.average_lot_manual_first_process = self.custom_round_down((total_manual_first_process / total_lines)) if total_lines else 0.0
            move.average_lot_manual_product_quality = self.custom_round_down((total_manual_product_quality / total_lines)) if total_lines else 0.0

    @api.depends('move_line_ids.mo_product_quality', 'move_line_ids.mo_first_process_wt', 'display_quantity')
    def _compute_total_weighted_average(self):
        for move in self:
            total_quantity =  move.display_quantity
            # total_quality = self.custom_round_down(sum(line.lot_product_quality for line in move.move_line_ids))
            # NOTE  divide by totalquantity not totalquality
            total_weighted_quality = sum(line.mo_product_quality * line.mo_first_process_wt for line in move.move_line_ids)
            move.total_weighted_average = self.custom_round_down(total_weighted_quality / move.display_quantity) if total_quantity else 0.0

    @api.depends('move_line_ids', 'move_line_ids.lot_id', 'move_line_ids.mo_first_process_wt', 'move_line_ids.mo_manual_product_quality')
    def _compute_total_weighted_average_manual(self):
        for move in self:
            total_quantity =  move.display_quantity
            total_weighted_quality = sum(line.mo_manual_product_quality * line.mo_first_process_wt for line in move.move_line_ids)
            move.total_weighted_average_manual = self.custom_round_down(total_weighted_quality / move.display_quantity) if total_quantity else 0.0

    @api.depends('move_line_ids', 'move_line_ids.lot_id', 'move_line_ids.mo_first_process_wt')
    def _compute_display_quantity(self):
        for move in self:
            lot_quantity = 0.0
            for line in move.move_line_ids:
                if line.mo_first_process_wt:
                    lot_quantity += line.mo_first_process_wt
            move.display_quantity = lot_quantity

    @api.depends('move_line_ids', 'move_line_ids.lot_id', 'move_line_ids.mo_purchase_cost')
    def _compute_total_purchase_cost(self):
        for move in self:
            lot_cost = 0.0
            for line in move.move_line_ids:
                if line.mo_purchase_cost:
                    lot_cost += line.mo_purchase_cost
            move.total_purchase_cost = lot_cost

    @api.depends('move_line_ids', 'move_line_ids.lot_id', 'move_line_ids.mo_net_price', 'move_line_ids.mo_first_process_wt')
    def _compute_total_net_price(self):
        for move in self:
            gtotal = 0.0
            total_mfp = 0.0
            for line in move.move_line_ids:
                if line.mo_net_price and line.mo_first_process_wt:
                    gtotal += line.mo_first_process_wt * line.mo_net_price
                    total_mfp += line.mo_first_process_wt
            move.total_net_price = gtotal / total_mfp if total_mfp > 0 else 0.0

    @api.depends('move_line_ids.mo_original_subTotal')
    def _compute_original_subtotal(self):
        for move in self:
            subtotal = 0.0
            for line in move.move_line_ids:
                if line.mo_original_subTotal:
                    subtotal += line.mo_original_subTotal
            move.total_original_subTotal = subtotal

    def _action_assign(self, force_qty=False):
            """ Reserve stock moves by creating their stock move lines, bypassing FIFO for manually assigned lots and supporting multiple lots. """
            StockMove = self.env['stock.move']
            assigned_moves_ids = OrderedSet()
            partially_available_moves_ids = OrderedSet()
            # Read the `reserved_availability` field of the moves out of the loop to prevent unwanted
            # cache invalidation when actually reserving the move.
            reserved_availability = {move: move.reserved_availability for move in self}
            roundings = {move: move.product_id.uom_id.rounding for move in self}
            move_line_vals_list = []
            # Once the quantities are assigned, we want to find a better destination location thanks
            # to the putaway rules. This redirection will be applied on moves of `moves_to_redirect`.
            moves_to_redirect = OrderedSet()
            moves_to_assign = self
            if not force_qty:
                moves_to_assign = self.filtered(lambda m: m.state in ['confirmed', 'waiting', 'partially_available'])

            moves_mto = moves_to_assign.filtered(lambda m: m.move_orig_ids and not m._should_bypass_reservation())

            for move in moves_to_assign:
                rounding = roundings[move]
                if not force_qty:
                    missing_reserved_uom_quantity = move.product_uom_qty
                else:
                    missing_reserved_uom_quantity = force_qty
                missing_reserved_uom_quantity -= reserved_availability[move]
                missing_reserved_quantity = move.product_uom._compute_quantity(missing_reserved_uom_quantity, move.product_id.uom_id, rounding_method='HALF-UP')

                if move._should_bypass_reservation():
                    # Handle moves that bypass reservation (e.g., MTO)
                    if move.move_orig_ids:
                        available_move_lines = move._get_available_move_lines(assigned_moves_ids, partially_available_moves_ids)
                        for (location_id, lot_id, package_id, owner_id), quantity in available_move_lines.items():
                            qty_added = min(missing_reserved_quantity, quantity)
                            move_line_vals = move._prepare_move_line_vals(qty_added)
                            move_line_vals.update({
                                'location_id': location_id.id,
                                'lot_id': lot_id.id,
                                'lot_name': lot_id.name,
                                'owner_id': owner_id.id,
                                'package_id': package_id.id,
                            })
                            move_line_vals_list.append(move_line_vals)
                            missing_reserved_quantity -= qty_added
                            if float_is_zero(missing_reserved_quantity, precision_rounding=move.product_id.uom_id.rounding):
                                break

                    if missing_reserved_quantity and move.product_id.tracking == 'serial' and (move.picking_type_id.use_create_lots or move.picking_type_id.use_existing_lots):
                        for i in range(0, int(missing_reserved_quantity)):
                            move_line_vals_list.append(move._prepare_move_line_vals(quantity=1))
                    elif missing_reserved_quantity:
                        # Check for existing move lines with manually assigned lots
                        manual_lots = move.move_line_ids.filtered(lambda ml: ml.lot_id).mapped('lot_id')  # Get all lots
                        if manual_lots:
                            remaining_quantity = missing_reserved_quantity
                            for lot in manual_lots:
                                # Get quants for this specific lot, location, and product
                                quants = self.env['stock.quant'].search([
                                    ('product_id', '=', move.product_id.id),
                                    ('location_id', '=', move.location_id.id),
                                    ('lot_id', '=', lot.id),
                                    ('quantity', '>', 0),
                                ])
                                available_quantity = sum(q.quantity for q in quants)
                                if available_quantity > 0:
                                    qty_to_reserve = min(remaining_quantity, available_quantity)
                                    taken_quantity = move._update_reserved_quantity(qty_to_reserve, qty_to_reserve, move.location_id, lot_id=lot, strict=False)
                                    if float_is_zero(taken_quantity, precision_rounding=rounding):
                                        continue
                                    move_line_vals = move._prepare_move_line_vals(taken_quantity, lot_id=lot.id)
                                    move_line_vals.update({
                                        'location_id': move.location_id.id,
                                    })
                                    move_line_vals_list.append(move_line_vals)
                                    remaining_quantity -= taken_quantity
                                    if float_is_zero(remaining_quantity, precision_rounding=rounding):
                                        break
                            # Do not fall back to FIFO if manually selected lots are not sufficient
                            if not float_is_zero(remaining_quantity, precision_rounding=rounding):
                                raise UserError(_("Not enough quantity available for the selected lots."))
                        else:
                            move_line_vals_list.append(move._prepare_move_line_vals(quantity=missing_reserved_quantity))
                    assigned_moves_ids.add(move.id)
                    moves_to_redirect.add(move.id)
                else:
                    if float_is_zero(move.product_uom_qty, precision_rounding=move.product_uom.rounding):
                        assigned_moves_ids.add(move.id)
                    elif not move.move_orig_ids:
                        if move.procure_method == 'make_to_order':
                            continue
                        # If we don't need any quantity, consider the move assigned.
                        need = missing_reserved_quantity
                        if float_is_zero(need, precision_rounding=rounding):
                            assigned_moves_ids.add(move.id)
                            continue
                        # Reserve new quants, bypassing FIFO for manually assigned lots
                        forced_package_id = move.package_level_id.package_id or None
                        # Check for manually assigned lots first
                        manual_lots = move.move_line_ids.filtered(lambda ml: ml.lot_id).mapped('lot_id')  # Get all lots
                        if manual_lots:
                            remaining_quantity = need
                            for lot in manual_lots:
                                # Get quants for this specific lot, location, and product
                                quants = self.env['stock.quant'].search([
                                    ('product_id', '=', move.product_id.id),
                                    ('location_id', '=', move.location_id.id),
                                    ('lot_id', '=', lot.id),
                                    ('quantity', '>', 0),
                                ])
                                available_quantity = sum(q.quantity for q in quants)
                                if available_quantity > 0:
                                    qty_to_reserve = min(remaining_quantity, available_quantity)
                                    taken_quantity = move._update_reserved_quantity(qty_to_reserve, qty_to_reserve, move.location_id, lot_id=lot, package_id=forced_package_id, strict=False)
                                    if float_is_zero(taken_quantity, precision_rounding=rounding):
                                        continue
                                    moves_to_redirect.add(move.id)
                                    if float_compare(remaining_quantity, taken_quantity, precision_rounding=rounding) == 0:
                                        assigned_moves_ids.add(move.id)
                                    else:
                                        partially_available_moves_ids.add(move.id)
                                    remaining_quantity -= taken_quantity
                                    if float_is_zero(remaining_quantity, precision_rounding=rounding):
                                        break
                            if not float_is_zero(remaining_quantity, precision_rounding=rounding):
                                # Fall back to available quants (without FIFO sorting) for remaining quantity
                                #  raise UserError(_("Not enough quantity available for the selected lots."))
                                available_quantity = move._get_available_quantity(move.location_id, package_id=forced_package_id)
                                if available_quantity > 0:
                                    taken_quantity = move._update_reserved_quantity(remaining_quantity, available_quantity, move.location_id, package_id=forced_package_id, strict=False)
                                    if not float_is_zero(taken_quantity, precision_rounding=rounding):
                                        moves_to_redirect.add(move.id)
                                        if float_compare(remaining_quantity, taken_quantity, precision_rounding=rounding) == 0:
                                            assigned_moves_ids.add(move.id)
                                        else:
                                            partially_available_moves_ids.add(move.id)
                        else:
                            # If no manual lots, fall back to available quants (without FIFO sorting)
                            available_quantity = move._get_available_quantity(move.location_id, package_id=forced_package_id)
                            if available_quantity <= 0:
                                continue
                            taken_quantity = move._update_reserved_quantity(need, available_quantity, move.location_id, package_id=forced_package_id, strict=False)
                            if float_is_zero(taken_quantity, precision_rounding=rounding):
                                continue
                            moves_to_redirect.add(move.id)
                            if float_compare(need, taken_quantity, precision_rounding=rounding) == 0:
                                assigned_moves_ids.add(move.id)
                            else:
                                partially_available_moves_ids.add(move.id)
                    else:
                        # Handle chained moves, respecting manually assigned lots
                        available_move_lines = move._get_available_move_lines(assigned_moves_ids, partially_available_moves_ids)
                        manual_lots = move.move_line_ids.filtered(lambda ml: ml.lot_id).mapped('lot_id')  # Get all lots
                        if manual_lots:
                            need = move.product_qty - sum(move.move_line_ids.mapped('reserved_qty'))
                            remaining_quantity = need
                            for lot in manual_lots:
                                if (move.location_id, lot, None, None) in available_move_lines:
                                    quantity = available_move_lines[(move.location_id, lot, None, None)]
                                    available_quantity = move._get_available_quantity(move.location_id, lot_id=lot, strict=True)
                                    if float_is_zero(available_quantity, precision_rounding=rounding):
                                        continue
                                    qty_to_reserve = min(remaining_quantity, quantity, available_quantity)
                                    taken_quantity = move._update_reserved_quantity(qty_to_reserve, qty_to_reserve, move.location_id, lot_id=lot)
                                    if float_is_zero(taken_quantity, precision_rounding=rounding):
                                        continue
                                    moves_to_redirect.add(move.id)
                                    if float_compare(remaining_quantity - taken_quantity, precision_rounding=rounding) == 0:
                                        assigned_moves_ids.add(move.id)
                                        break
                                    partially_available_moves_ids.add(move.id)
                                    remaining_quantity -= taken_quantity
                                    if float_is_zero(remaining_quantity, precision_rounding=rounding):
                                        break
                        else:
                            # Fall back to available move lines without FIFO sorting
                            for (location_id, lot_id, package_id, owner_id), quantity in available_move_lines.items():
                                need = move.product_qty - sum(move.move_line_ids.mapped('reserved_qty'))
                                available_quantity = move._get_available_quantity(location_id, lot_id=lot_id, package_id=package_id, owner_id=owner_id, strict=True)
                                if float_is_zero(available_quantity, precision_rounding=rounding):
                                    continue
                                taken_quantity = move._update_reserved_quantity(need, min(quantity, available_quantity), location_id, lot_id, package_id, owner_id)
                                if float_is_zero(taken_quantity, precision_rounding=rounding):
                                    continue
                                moves_to_redirect.add(move.id)
                                if float_compare(need - taken_quantity, precision_rounding=rounding) == 0:
                                    assigned_moves_ids.add(move.id)
                                    break
                                partially_available_moves_ids.add(move.id)

                if move.product_id.tracking == 'serial':
                    move.next_serial_count = move.product_uom_qty

            self.env['stock.move.line'].create(move_line_vals_list)
            StockMove.browse(partially_available_moves_ids).write({'state': 'partially_available'})
            StockMove.browse(assigned_moves_ids).write({'state': 'assigned'})
            if not self.env.context.get('bypass_entire_pack'):
                self.picking_id._check_entire_pack()
            StockMove.browse(moves_to_redirect).move_line_ids._apply_putaway_strategy()

class StockQuant(models.Model):
    _inherit = "stock.quant"

    product_quality = fields.Float(string="Product Quality")
    first_process_wt = fields.Float(string="First Process Wt")
    manual_first_process = fields.Float(string="Manual First Process Wt")

    @api.model
    def create(self, vals):
        quant = super(StockQuant, self).create(vals)
        if quant.product_id:
            # Search for the most recent stock move for this product and location
            move = self.env['stock.move'].search([
                ('product_id', '=', quant.product_id.id),
                ('location_dest_id', '=', quant.location_id.id),
                ('state', '=', 'done')
            ], order='date desc', limit=1)

            if move:
                quant.write({
                    'product_quality': move.product_quality,
                    'first_process_wt': move.first_process_wt,
                    'manual_first_process': move.manual_first_process,
                })
        return quant

