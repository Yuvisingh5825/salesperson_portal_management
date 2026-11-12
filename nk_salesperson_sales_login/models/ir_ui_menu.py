# -*- coding: utf-8 -*-
"""
Field Salesperson users see ONLY the "Field Salesperson" app.

Every other menu (Apps, Settings, Discuss, Sales ... and any app installed
in the future) is hidden for them.

Who is affected:
    users in group "Field Salesperson"
    who are NOT in "Field Salesperson Manager"
    and NOT Administrator (Settings).
Managers and Administrators keep the normal menus.
"""

from odoo import api, models

NK_USER = "nk_salesperson_sales_login.group_nk_salesperson"
NK_MANAGER = "nk_salesperson_sales_login.group_nk_salesperson_manager"
NK_ROOT_MENU = "nk_salesperson_sales_login.menu_nk_salesperson_root"


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def _visible_menu_ids(self, debug=False):
        visible = super()._visible_menu_ids(debug=debug)

        user = self.env.user
        if (
            not user.has_group(NK_USER)
            or user.has_group(NK_MANAGER)
            or user.has_group("base.group_system")
        ):
            return visible

        root = self.env.ref(NK_ROOT_MENU, raise_if_not_found=False)
        if not root:
            return visible

        nk_menus = self.with_context(
            **{"ir.ui.menu.full_list": True}
        ).sudo().search([("id", "child_of", root.id)])

        # new set: the cached value of super() must never be changed
        return set(visible) & set(nk_menus.ids)
