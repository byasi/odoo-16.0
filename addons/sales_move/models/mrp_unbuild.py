from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class MrpUnbuild(models.Model):
    _inherit = 'mrp.unbuild'

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _compute_mo_produced_qty(self):
        """
        Compute the produced quantity for the MO from finished move lines.
        Falls back to finished moves.quantity_done, and lastly to MO.product_qty.
        This avoids the zero division and missing qty_produced issues.
        """
        self.ensure_one()
        if not self.mo_id:
            return 0.0

        # Sum finished move lines qty_done for the finished product
        finished_moves = self.mo_id.move_finished_ids.filtered(
            lambda m: m.state == 'done' and m.product_id == self.mo_id.product_id
        )
        produced = sum(finished_moves.mapped('move_line_ids').filtered(
            lambda ml: ml.qty_done > 0).mapped('qty_done'))

        # Fallback to move.quantity_done if move lines are empty
        if float_is_zero(produced, precision_rounding=self.product_uom_id.rounding):
            produced = sum(finished_moves.mapped('quantity_done'))

        # Final fallback to MO planned qty (best-effort)
        if float_is_zero(produced, precision_rounding=self.product_uom_id.rounding):
            produced = self.mo_id.product_qty

        return produced

    def _prepare_move_line_vals(self, move, origin_move_line, taken_quantity):
        """
        Override to ensure lot_id is properly set from origin_move_line.
        This fixes the issue where unbuild fails when raw material move lines don't have lot_id.
        """
        vals = {
            'move_id': move.id,
            'qty_done': taken_quantity,
            'product_id': move.product_id.id,
            'product_uom_id': origin_move_line.product_uom_id.id,
            'location_id': move.location_id.id,
            'location_dest_id': move.location_dest_id.id,
        }
        
        # Set lot_id from origin_move_line if available
        # Use .id to safely get the ID (returns False if lot_id is False/None)
        lot_id = origin_move_line.lot_id.id if origin_move_line.lot_id else False
        if lot_id:
            vals['lot_id'] = lot_id
        elif move.product_id.tracking != 'none':
            # If product requires tracking but origin_move_line doesn't have lot_id,
            # try to recover a lot from other move lines of this MO for the same product.
            if self.mo_id:
                # Prefer move lines on the same raw move (if any)
                same_move_lines = origin_move_line.move_id.move_line_ids.filtered(lambda ml: ml.lot_id)
                if same_move_lines:
                    vals['lot_id'] = same_move_lines[0].lot_id.id
                else:
                    # Look across all raw moves of the MO for this product
                    mo_move_lines = self.mo_id.move_raw_ids.filtered(
                        lambda m: m.product_id == move.product_id
                    ).mapped('move_line_ids').filtered(lambda ml: ml.lot_id)
                    if mo_move_lines:
                        vals['lot_id'] = mo_move_lines[0].lot_id.id

            # If still no lot, raise an explicit error with guidance
            if 'lot_id' not in vals:
                raise UserError(_(
                    "You need to supply a Lot/Serial Number for product '%s' on the unbuild. "
                    "Please select a lot on the original raw material move lines for this MO, then retry."
                ) % move.product_id.display_name)

        return vals

    def _generate_produce_moves(self):
        """
        Override to avoid zero-division and missing qty_produced issues.
        We compute produced qty from finished move lines (or moves) and fall back to planned qty.
        """
        moves = self.env['stock.move']
        for unbuild in self:
            if unbuild.mo_id:
                raw_moves = unbuild.mo_id.move_raw_ids.filtered(lambda move: move.state == 'done')

                # Compute produced qty safely (handles missing qty_produced)
                produced_qty = unbuild._compute_mo_produced_qty()
                computed_qty = unbuild.mo_id.product_uom_id._compute_quantity(
                    produced_qty, unbuild.product_uom_id
                )

                if float_is_zero(computed_qty, precision_rounding=unbuild.product_uom_id.rounding):
                    raise UserError(_(
                        'Cannot unbuild: The manufacturing order "%s" has zero produced quantity. '
                        'Please check finished moves/lines or produce quantity before unbuilding.'
                    ) % unbuild.mo_id.name)

                factor = unbuild.product_qty / computed_qty
                for raw_move in raw_moves:
                    moves += unbuild._generate_move_from_existing_move(
                        raw_move, factor, raw_move.location_dest_id, self.location_dest_id
                    )
            else:
                # Handle the case without manufacturing order (using BOM directly)
                factor = unbuild.product_uom_id._compute_quantity(
                    unbuild.product_qty, unbuild.bom_id.product_uom_id
                ) / unbuild.bom_id.product_qty
                
                # Check if BOM quantity is zero
                if float_is_zero(unbuild.bom_id.product_qty, precision_rounding=unbuild.bom_id.product_uom_id.rounding):
                    raise UserError(_(
                        'Cannot unbuild: The Bill of Material "%s" has zero product quantity. '
                        'Please check the BOM configuration.'
                    ) % unbuild.bom_id.display_name)
                
                boms, lines = unbuild.bom_id.explode(
                    unbuild.product_id, factor, picking_type=unbuild.bom_id.picking_type_id
                )
                for line, line_data in lines:
                    moves += unbuild._generate_move_from_bom_line(
                        line.product_id, line.product_uom_id, line_data['qty'], bom_line_id=line.id
                    )
        return moves

    def action_validate(self):
        """
        Ensure a lot is set for tracked products before validating.
        If missing, attempt to auto-fill from finished move lines (or lot_producing_id).
        """
        for unbuild in self:
            if unbuild.product_id.tracking != 'none' and not unbuild.lot_id:
                lot = False
                if unbuild.mo_id:
                    finished_moves = unbuild.mo_id.move_finished_ids.filtered(
                        lambda m: m.state == 'done' and m.product_id == unbuild.product_id
                    )
                    move_line_lots = finished_moves.mapped('move_line_ids').filtered(
                        lambda ml: ml.lot_id
                    ).mapped('lot_id')
                    if move_line_lots:
                        lot = move_line_lots[0]
                    elif unbuild.mo_id.lot_producing_id:
                        lot = unbuild.mo_id.lot_producing_id
                if lot:
                    unbuild.lot_id = lot.id
        return super().action_validate()
