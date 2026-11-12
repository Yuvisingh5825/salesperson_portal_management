# -*- coding: utf-8 -*-

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import html_escape


class SaleOrder(models.Model):
    _inherit = "sale.order"

    nk_employee_id = fields.Many2one(
        "hr.employee",
        string="Salesperson",
        copy=True,
        index=True,
        default=lambda self: self._get_current_nk_employee(),
    )
    nk_visit_id = fields.Many2one(
        "nk.salesperson.visit",
        string="Salesperson Visit",
        index=True,
        ondelete="set null",
    )

    ionex_survey_id = fields.Many2one(
        "ionex.survey",
        string="Survey",
        copy=False,
        index=True,
        readonly=True,
        ondelete="set null",
    )
    ionex_survey_type = fields.Selection(
        related="ionex_survey_id.survey_type",
        string="Survey Type",
        store=True,
    )

    # ---- Reject quotation ----
    nk_is_rejected = fields.Boolean(
        string="Rejected",
        copy=False,
        index=True,
        readonly=True,
    )
    nk_reject_reason = fields.Text(
        string="Reject Reason",
        copy=False,
        readonly=True,
    )
    nk_reject_date = fields.Datetime(
        string="Rejected On",
        copy=False,
        readonly=True,
    )

    # =========================================================
    # GET CURRENT EMPLOYEE
    # =========================================================

    @api.model
    def _get_current_nk_employee(self):
        """
        Get employee from the custom Field Salesperson login session.
        """

        try:
            from odoo.http import request

            employee_id = request.session.get(
                "nk_salesperson_employee_id"
            )

            if not employee_id:
                return False

            employee = (
                self.env["hr.employee"]
                .sudo()
                .browse(int(employee_id))
                .exists()
            )

            if employee:
                return employee.id

        except Exception:
            pass

        return False

    # =========================================================
    # CREATE
    # =========================================================

    @api.model_create_multi
    def create(self, vals_list):
        """
        Automatically assign the logged-in employee
        to newly created quotations.
        """

        current_employee_id = self._get_current_nk_employee()

        for vals in vals_list:

            if (
                current_employee_id
                and not vals.get("nk_employee_id")
            ):
                vals["nk_employee_id"] = current_employee_id

        return super().create(vals_list)

    # =========================================================
    # SEARCH
    # =========================================================

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        """
        Manager / admin / normal Odoo users -> normal behaviour.
        salesperson -> only own quotations (by login session).
        All extra kwargs (active_test, bypass_access ...) are passed
        through untouched so this works on any Odoo version.
        """
        if self.env.su:
            return super()._search(
                domain, offset=offset, limit=limit, order=order, **kwargs
            )

        user = self.env.user
        is_manager = (
            user.has_group("base.group_system")
            or user.has_group("sales_team.group_sale_manager")
            or user.has_group(
                "nk_salesperson_sales_login.group_nk_salesperson_manager"
            )
        )

        if not is_manager and user.has_group(
            "nk_salesperson_sales_login.group_nk_salesperson"
        ):
            current_employee_id = self._get_current_nk_employee()
            extra = (
                [("nk_employee_id", "=", current_employee_id)]
                if current_employee_id
                else [("id", "=", False)]
            )
            domain = Domain(domain) & Domain(extra)

        return super()._search(
            domain, offset=offset, limit=limit, order=order, **kwargs
        )

    # =========================================================
    # SAVE & BACK TO DASHBOARD
    # =========================================================

    def action_save_and_nk_dashboard(self):

        self.ensure_one()

        return {
            "type": "ir.actions.act_url",
            "url": "/nk_salesperson/quotation/%s" % self.id,
            "target": "self",
        }

    # =========================================================
    # REJECT QUOTATION
    # =========================================================

    def action_nk_reject(self):
        """Open the wizard where the reject reason is written."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Reject Quotation",
            "res_model": "nk.quotation.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_order_id": self.id},
        }

    def nk_reject_quotation(self, reason):
        """Reject quotation(s) with a reason.

        Used by the backend wizard and by the portal.
        The quotation is cancelled (state = cancel) and the reason is saved.
        """
        reason = (reason or "").strip()
        if not reason:
            raise UserError("Please write the reject reason.")

        for order in self.sudo():
            if order.state not in ("draft", "sent"):
                raise UserError(
                    "Only a quotation can be rejected. "
                    "%s is not a quotation." % order.name
                )
            order.write({
                "nk_is_rejected": True,
                "nk_reject_reason": reason,
                "nk_reject_date": fields.Datetime.now(),
            })
            order._action_cancel()
            order.message_post(
                body="Quotation rejected. Reason: " + html_escape(reason)
            )
        return True
