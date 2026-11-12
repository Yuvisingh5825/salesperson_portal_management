# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import api, fields, models


class NkSalespersonVisit(models.Model):
    _name = "nk.salesperson.visit"
    _description = "Field Salesperson Visit"
    _order = "visit_date desc, id desc"

    name = fields.Char(
        string="Visit Reference",
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

    visit_date = fields.Date(
        string="Visit Date",
        required=True,
        default=fields.Date.context_today,
    )

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

    # Multiple quotations can belong to one visit
    quotation_ids = fields.One2many(
        "sale.order",
        "nk_visit_id",
        string="Quotations",
    )

    # Multiple expenses can belong to one visit
    expense_ids = fields.One2many(
        "nk.salesperson.expense",
        "visit_id",
        string="Expenses",
    )

    location_point_ids = fields.One2many(
        "nk.location.point",
        "visit_id",
        string="Tracked Locations",
    )

    state = fields.Selection(
        [
            ("open", "Open"),
            ("closed", "Closed"),
        ],
        string="Status",
        default="open",
        required=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code(
                        "nk.salesperson.visit"
                    )
                    or "New"
                )

        visits = super().create(vals_list)
        visits._nk_link_last_location()
        return visits

    def _nk_link_last_location(self):
        """Fill GPS of a new visit from the salesperson's latest tracked
        location (only if tracking sent a location recently)."""
        Point = self.env["nk.location.point"].sudo()
        stale = self.env["nk.tracking.session"]._stale_minutes()
        limit = fields.Datetime.now() - timedelta(minutes=stale)

        for visit in self:
            if visit.latitude or visit.longitude:
                continue
            point = Point.search([
                ("employee_id", "=", visit.employee_id.id),
                ("timestamp", ">=", limit),
            ], order="timestamp desc, id desc", limit=1)
            if point:
                visit.write({
                    "latitude": point.latitude,
                    "longitude": point.longitude,
                })
                point.visit_id = visit.id

    def action_close(self):
        self.write({
            "state": "closed"
        })
        return True

    def action_open(self):
        self.write({
            "state": "open"
        })
        return True
