# -*- coding: utf-8 -*-

import logging

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class NkSalespersonExpense(models.Model):
    _name = "nk.salesperson.expense"
    _description = "Field Salesperson Expense"
    _order = "expense_date desc, id desc"

    # =========================================================
    # BASIC INFORMATION
    # =========================================================

    name = fields.Char(
        string="Expense Reference",
        required=True,
        copy=False,
        readonly=True,
        default="New",
    )

    employee_id = fields.Many2one(
        "hr.employee",
        string="Salesperson",
        required=True,
        ondelete="restrict",
    )

    expense_date = fields.Date(
        string="Expense Date",
        required=True,
        default=fields.Date.context_today,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )

    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    # =========================================================
    # LINKED DATA
    # =========================================================
    # These fields are kept for OLD / LEGACY records and reports.
    # They are NOT required for new location-based expenses.
    # They should NOT be shown on the expense form.

    visit_id = fields.Many2one(
        "nk.salesperson.visit",
        string="Visit / Location",
        ondelete="set null",
    )

    partner_ids = fields.Many2many(
        "res.partner",
        "nk_salesperson_expense_partner_rel",
        "expense_id",
        "partner_id",
        string="Customers / Places",
    )

    quotation_ids = fields.Many2many(
        "sale.order",
        "nk_salesperson_expense_sale_rel",
        "expense_id",
        "sale_order_id",
        string="Linked Quotations",
    )

    # =========================================================
    # EXPENSE AMOUNTS
    # =========================================================

    travel_amount = fields.Monetary(
        string="Travel",
        currency_field="currency_id",
        default=0.0,
    )

    food_amount = fields.Monetary(
        string="Food",
        currency_field="currency_id",
        default=0.0,
    )

    hotel_amount = fields.Monetary(
        string="Hotel",
        currency_field="currency_id",
        default=0.0,
    )

    fuel_amount = fields.Monetary(
        string="Fuel",
        currency_field="currency_id",
        default=0.0,
    )

    mobile_amount = fields.Monetary(
        string="Mobile",
        currency_field="currency_id",
        default=0.0,
    )

    other_amount = fields.Monetary(
        string="Other",
        currency_field="currency_id",
        default=0.0,
    )

    total_expense = fields.Monetary(
        string="Total Expense",
        currency_field="currency_id",
        compute="_compute_total_expense",
        store=True,
    )

    # =========================================================
    # LOCATION
    # =========================================================

    location = fields.Char(
        string="Location",
        required=True,
    )

    address = fields.Text(
        string="Address",
    )

    latitude = fields.Float(
        string="Latitude",
        digits=(10, 7),
    )

    longitude = fields.Float(
        string="Longitude",
        digits=(10, 7),
    )

    # =========================================================
    # DESCRIPTION / RECEIPT
    # =========================================================

    description = fields.Text(
        string="Description",
    )

    receipt = fields.Binary(
        string="Receipt",
        attachment=True,
    )

    receipt_filename = fields.Char(
        string="Receipt Filename",
    )

    # =========================================================
    # STATUS
    # =========================================================

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Status",
        default="draft",
        required=True,
        copy=False,
    )

    rejection_reason = fields.Text(
        string="Rejection Reason",
        copy=False,
    )

    # =========================================================
    # COMPUTE TOTAL EXPENSE
    # =========================================================

    @api.depends(
        "travel_amount",
        "food_amount",
        "hotel_amount",
        "fuel_amount",
        "mobile_amount",
        "other_amount",
    )
    def _compute_total_expense(self):
        for record in self:
            record.total_expense = (
                record.travel_amount
                + record.food_amount
                + record.hotel_amount
                + record.fuel_amount
                + record.mobile_amount
                + record.other_amount
            )

    # =========================================================
    # VALIDATE EXPENSE AMOUNTS
    # =========================================================

    @api.constrains(
        "travel_amount",
        "food_amount",
        "hotel_amount",
        "fuel_amount",
        "mobile_amount",
        "other_amount",
    )
    def _check_expense_amounts(self):
        for record in self:
            amounts = [
                record.travel_amount,
                record.food_amount,
                record.hotel_amount,
                record.fuel_amount,
                record.mobile_amount,
                record.other_amount,
            ]

            if any(amount < 0 for amount in amounts):
                raise ValidationError(
                    "Expense amount cannot be negative."
                )

    # =========================================================
    # CREATE
    # =========================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:

            # -------------------------------------------------
            # Clean location text (same place = same name)
            # -------------------------------------------------
            if vals.get("location"):
                vals["location"] = " ".join(vals["location"].split())

            # -------------------------------------------------
            # Generate Expense Reference
            # -------------------------------------------------
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code(
                        "nk.salesperson.expense"
                    )
                    or "New"
                )

            # -------------------------------------------------
            # Automatically assign logged-in employee
            # -------------------------------------------------
            if not vals.get("employee_id"):
                employee = self.env["hr.employee"].search(
                    [
                        ("user_id", "=", self.env.user.id),
                    ],
                    limit=1,
                )

                if employee:
                    vals["employee_id"] = employee.id

            # -------------------------------------------------
            # Automatically set company
            # -------------------------------------------------
            if not vals.get("company_id"):
                vals["company_id"] = self.env.company.id

            # -------------------------------------------------
            # Automatically set currency
            # -------------------------------------------------
            if not vals.get("currency_id"):
                vals["currency_id"] = self.env.company.currency_id.id

        return super().create(vals_list)

    def write(self, vals):
        if vals.get("location"):
            vals = dict(vals, location=" ".join(vals["location"].split()))
        return super().write(vals)

    # =========================================================
    # PLACE NAME FROM GPS
    # =========================================================

    @api.model
    def nk_lookup_place(self, latitude, longitude):
        """Return (place, address) for GPS coordinates.

        place   : city / town / village name (used for location wise report)
        address : short readable address

        Uses the same geocoding settings as location tracking
        (nk_salesperson.geocode_enabled / geocode_url / geocode_user_agent).
        Returns ("", "") when the lookup is off or fails.
        """
        Point = self.env["nk.location.point"].sudo()

        if not Point._geocode_enabled():
            return "", ""

        url = Point._geocode_url()
        if not url:
            return "", ""

        try:
            response = requests.get(
                url,
                params={
                    "format": "jsonv2",
                    "lat": latitude,
                    "lon": longitude,
                    "zoom": 17,
                    "addressdetails": 1,
                    "accept-language": "en",
                },
                headers={"User-Agent": Point._geocode_user_agent()},
                timeout=8,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as error:      # network / service problem
            _logger.warning("expense place lookup failed: %s", error)
            return "", ""

        details = data.get("address") or {}
        place = ""
        for key in (
            "city", "town", "village", "municipality", "suburb", "county",
        ):
            if details.get(key):
                place = details[key]
                break

        return place, (Point._format_address(data) or "")

    # =========================================================
    # SUBMIT EXPENSE
    # =========================================================

    def action_submit(self):
        for record in self:

            if record.state not in ("draft", "rejected"):
                continue

            # Location is mandatory
            if not record.location or not record.location.strip():
                raise UserError(
                    "Please enter the expense location before submitting."
                )

            # At least one expense amount required
            if record.total_expense <= 0:
                raise UserError(
                    "Please enter at least one expense amount before submitting."
                )

            # Salesperson required
            if not record.employee_id:
                raise UserError(
                    "Please select a salesperson."
                )

            record.write({
                "state": "submitted",
                "rejection_reason": False,
            })

        return True

    # =========================================================
    # APPROVE EXPENSE
    # =========================================================

    def action_approve(self):
        for record in self:

            if record.state != "submitted":
                continue

            if not record.location or not record.location.strip():
                raise UserError(
                    "Cannot approve an expense without a location."
                )

            if record.total_expense <= 0:
                raise UserError(
                    "Cannot approve an expense with zero amount."
                )

            record.write({
                "state": "approved",
                "rejection_reason": False,
            })

        return True

    # =========================================================
    # REJECT EXPENSE
    # =========================================================

    def action_reject(self):
        for record in self:

            if record.state != "submitted":
                continue

            record.write({
                "state": "rejected",
            })

        return True

    # =========================================================
    # RESET TO DRAFT
    # =========================================================

    def action_reset_to_draft(self):
        for record in self:

            record.write({
                "state": "draft",
                "rejection_reason": False,
            })

        return True
