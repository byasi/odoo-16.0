/** @odoo-module **/

import { ListController } from "@web/views/list/list_controller";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

patch(ListController.prototype, "sales_move", {

    setup(){
        this._super.apply();
        this.action = useService("action");
    },

    unfixedPriceBtnClickEvent(){
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Add Unfixed Price',
            view_mode: 'form',
            target: 'new',
            res_model: 'sale.order.unfixedpricewizard',
            views: [[false, 'form']],
            context: {
                active_ids: this.model.root.selection.map(record => record.id),
            },
        })
    }
});