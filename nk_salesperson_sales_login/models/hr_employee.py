# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    nk_employee_id = fields.Char(
        string="Employee ID",
        copy=False,
        index=True,
    )

    nk_password = fields.Char(
        string="Password",
        copy=False,
    )

    nk_salary = fields.Monetary(
        string="Monthly Salary",
        currency_field="nk_currency_id",
    )

    nk_mobile_expense = fields.Monetary(
        string="Mobile Expense",
        currency_field="nk_currency_id",
    )

    nk_currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )

    _nk_employee_id_company_unique = models.Constraint(
        "unique(nk_employee_id, company_id)",
        "Employee ID must be unique within the company.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            employee_id = vals.get("nk_employee_id")
            if employee_id:
                vals["nk_employee_id"] = employee_id.strip()

        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)

        employee_id = vals.get("nk_employee_id")
        if employee_id:
            vals["nk_employee_id"] = employee_id.strip()

        return super().write(vals)

    @api.constrains("nk_employee_id")
    def _check_nk_employee_id(self):
        for employee in self:
            employee_id = employee.nk_employee_id
            if employee_id and not employee_id.strip():
                raise ValidationError("Employee ID cannot be empty.")

    # =========================================================
    # LOCATION TRACKING - HISTORY
    # =========================================================

    def action_nk_open_history(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_url",
            "url": "/nk_salesperson/admin/tracking/history?employee_id=%s"
                   % self.id,
            "target": "new",
        }

    # =========================================================
    # LOCATION TRACKING - TODAY
    # =========================================================

    def action_nk_open_today_tracking(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_url",
            "url": "/nk_salesperson/admin/tracking/today?employee_id=%s"
                   % self.id,
            "target": "new",
        }
