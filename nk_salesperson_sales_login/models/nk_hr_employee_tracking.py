# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import fields, models


class HrEmployeeTracking(models.Model):
    _inherit = "hr.employee"

    nk_tracking_status = fields.Selection(
        [
            ("active", "Active"),
            ("no_signal", "No Signal"),
            ("offline", "Offline"),
        ],
        string="Tracking",
        compute="_compute_nk_tracking",
    )
    nk_last_latitude = fields.Float(
        string="Last Latitude", digits=(10, 7), compute="_compute_nk_tracking")
    nk_last_longitude = fields.Float(
        string="Last Longitude", digits=(10, 7), compute="_compute_nk_tracking")
    nk_last_accuracy = fields.Float(
        string="Last Accuracy (m)", compute="_compute_nk_tracking")
    nk_last_location_time = fields.Datetime(
        string="Last Update", compute="_compute_nk_tracking")
    nk_last_address = fields.Char(
        string="Last Address", compute="_compute_nk_tracking")
    nk_last_location_text = fields.Char(
        string="Last Location", compute="_compute_nk_tracking")
    nk_last_address = fields.Char(
        string="Last Place", compute="_compute_nk_tracking")

    def _compute_nk_tracking(self):
        Session = self.env["nk.tracking.session"].sudo()
        Point = self.env["nk.location.point"].sudo()
        stale = timedelta(minutes=Session._stale_minutes())
        now = fields.Datetime.now()

        for employee in self:
            session = Session.search([
                ("employee_id", "=", employee.id),
                ("state", "=", "active"),
            ], limit=1, order="id desc")
            point = Point.search(
                [("employee_id", "=", employee.id)],
                order="timestamp desc, id desc",
                limit=1,
            )

            employee.nk_last_latitude = point.latitude if point else 0.0
            employee.nk_last_longitude = point.longitude if point else 0.0
            employee.nk_last_address = point.address if point else False
            employee.nk_last_accuracy = point.accuracy if point else 0.0
            employee.nk_last_location_time = point.timestamp if point else False
            employee.nk_last_address = point.address if point else False
            employee.nk_last_location_text = (
                "%.5f, %.5f" % (point.latitude, point.longitude)
                if point else False
            )

            if session:
                reference = session.start_time
                if point and point.timestamp > reference:
                    reference = point.timestamp
                employee.nk_tracking_status = (
                    "active" if now - reference <= stale else "no_signal"
                )
            else:
                employee.nk_tracking_status = "offline"

    def action_nk_open_history(self):
        """Row click in the tracking list -> location history page."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/nk_salesperson/admin/tracking/history?employee_id=%s"
                   % self.id,
            "target": "new",
        }
