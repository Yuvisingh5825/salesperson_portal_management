# -*- coding: utf-8 -*-
"""
Controlled location tracking.

* The salesperson must press "Start Tracking" (browser asks GPS permission).
* The salesperson can press "Stop Tracking" at any time.
* Every location is saved with latitude, longitude, accuracy, time and session.
* Old locations are deleted automatically (retention days).

Settings (Settings > Technical > System Parameters):

    nk_salesperson.location_retention_days
        default 90
        0 = keep forever

    nk_salesperson.location_interval_minutes
        default 3

    nk_salesperson.location_stale_minutes
        default 10

    nk_salesperson.geocode_enabled
        default 1

    nk_salesperson.geocode_url
        default OpenStreetMap Nominatim

    nk_salesperson.geocode_user_agent
        default FieldSalesperson/1.0
"""

import logging
import time as _time
from datetime import timedelta

import requests

from odoo import api, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)

PARAM = "nk_salesperson."


# ==============================================================
# TRACKING SESSION
# ==============================================================

class NkTrackingSession(models.Model):
    _name = "nk.tracking.session"
    _description = "Field Salesperson Tracking Session"
    _order = "start_time desc, id desc"

    name = fields.Char(
        string="Session",
        compute="_compute_name",
    )

    employee_id = fields.Many2one(
        "hr.employee",
        string="Salesperson",
        required=True,
        index=True,
        ondelete="cascade",
    )

    start_time = fields.Datetime(
        string="Started",
        required=True,
        default=fields.Datetime.now,
    )

    end_time = fields.Datetime(
        string="Stopped",
    )

    state = fields.Selection(
        [
            ("active", "Active"),
            ("stopped", "Stopped"),
        ],
        string="Status",
        default="active",
        required=True,
        index=True,
    )

    point_ids = fields.One2many(
        "nk.location.point",
        "session_id",
        string="Locations",
    )

    point_count = fields.Integer(
        string="Locations",
        compute="_compute_last",
    )

    last_latitude = fields.Float(
        string="Last Latitude",
        digits=(10, 7),
        compute="_compute_last",
    )

    last_longitude = fields.Float(
        string="Last Longitude",
        digits=(10, 7),
        compute="_compute_last",
    )

    last_update = fields.Datetime(
        string="Last Update",
        compute="_compute_last",
    )

    # ==========================================================
    # COMPUTE
    # ==========================================================

    def _compute_name(self):
        for session in self:
            session.name = "Session #%s" % (
                session.id or "New"
            )

    @api.depends("point_ids.timestamp")
    def _compute_last(self):
        for session in self:

            points = session.point_ids.sorted(
                lambda p: (p.timestamp, p.id)
            )

            last = points[-1:] if points else points

            session.point_count = len(points)

            session.last_latitude = (
                last.latitude
                if last
                else 0.0
            )

            session.last_longitude = (
                last.longitude
                if last
                else 0.0
            )

            session.last_update = (
                last.timestamp
                if last
                else False
            )

    # ==========================================================
    # SETTINGS
    # ==========================================================

    @api.model
    def _param_int(self, key, default):
        value = self.env[
            "ir.config_parameter"
        ].sudo().get_param(
            PARAM + key
        )

        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @api.model
    def _stale_minutes(self):
        return max(
            self._param_int(
                "location_stale_minutes",
                10,
            ),
            1,
        )

    @api.model
    def _interval_seconds(self):
        return max(
            self._param_int(
                "location_interval_minutes",
                3,
            ),
            1,
        ) * 60

    # ==========================================================
    # ACTIONS
    # ==========================================================

    @api.model
    def start_for_employee(self, employee):
        """
        Return the active session of the employee.
        Create one if no active session exists.
        """

        session = self.sudo().search(
            [
                ("employee_id", "=", employee.id),
                ("state", "=", "active"),
            ],
            limit=1,
        )

        return (
            session
            or self.sudo().create(
                {
                    "employee_id": employee.id,
                }
            )
        )

    def add_point(
        self,
        latitude,
        longitude,
        accuracy=0.0,
    ):
        """
        Save one GPS location.

        If the previous point was saved less than
        20 seconds ago, reuse that point.
        """

        self.ensure_one()

        Point = self.env[
            "nk.location.point"
        ].sudo()

        last = Point.search(
            [
                ("session_id", "=", self.id),
            ],
            order="timestamp desc, id desc",
            limit=1,
        )

        if (
            last
            and (
                fields.Datetime.now()
                - last.timestamp
            ) < timedelta(seconds=20)
        ):
            return last

        return Point.create(
            {
                "session_id": self.id,
                "latitude": latitude,
                "longitude": longitude,
                "accuracy": accuracy,
            }
        )

    def action_stop(self):

        self.filtered(
            lambda s: s.state == "active"
        ).write(
            {
                "state": "stopped",
                "end_time": fields.Datetime.now(),
            }
        )

        return True

    # ==========================================================
    # CRON - CLOSE STALE SESSIONS
    # ==========================================================

    @api.model
    def _cron_close_stale_sessions(self):
        """
        Close sessions that sent nothing for 12 hours.
        """

        limit = (
            fields.Datetime.now()
            - timedelta(hours=12)
        )

        for session in self.search(
            [
                ("state", "=", "active"),
            ]
        ):

            last = (
                session.last_update
                or session.start_time
            )

            if last < limit:

                session.write(
                    {
                        "state": "stopped",
                        "end_time": last,
                    }
                )

    # ==========================================================
    # CRON - PURGE OLD POINTS
    # ==========================================================

    @api.model
    def _cron_purge_old_points(self):
        """
        Delete locations older than retention period.
        """

        days = self._param_int(
            "location_retention_days",
            90,
        )

        if days <= 0:
            return

        cutoff = (
            fields.Datetime.now()
            - timedelta(days=days)
        )

        self.env[
            "nk.location.point"
        ].sudo().search(
            [
                ("timestamp", "<", cutoff),
            ]
        ).unlink()

        self.sudo().search(
            [
                ("state", "=", "stopped"),
                ("end_time", "<", cutoff),
                ("point_ids", "=", False),
            ]
        ).unlink()


# ==============================================================
# LOCATION POINT
# ==============================================================

class NkLocationPoint(models.Model):
    _name = "nk.location.point"
    _description = "Field Salesperson Location"
    _order = "timestamp desc, id desc"

    session_id = fields.Many2one(
        "nk.tracking.session",
        string="Session",
        required=True,
        index=True,
        ondelete="cascade",
    )

    employee_id = fields.Many2one(
        "hr.employee",
        string="Salesperson",
        related="session_id.employee_id",
        store=True,
        index=True,
    )

    latitude = fields.Float(
        string="Latitude",
        digits=(10, 7),
        required=True,
    )

    longitude = fields.Float(
        string="Longitude",
        digits=(10, 7),
        required=True,
    )

    accuracy = fields.Float(
        string="Accuracy (m)",
        digits=(10, 1),
    )

    timestamp = fields.Datetime(
        string="Date/Time",
        required=True,
        default=fields.Datetime.now,
        index=True,
    )

    visit_id = fields.Many2one(
        "nk.salesperson.visit",
        string="Visit",
        ondelete="set null",
    )

    # IMPORTANT:
    # Only ONE address field.
    address = fields.Char(
        string="Address",
    )

    geocode_tries = fields.Integer(
        string="Place Lookup Tries",
        default=0,
    )

    maps_url = fields.Char(
        string="Map Link",
        compute="_compute_maps_url",
    )

    # ==========================================================
    # GOOGLE MAPS URL
    # ==========================================================

    def _compute_maps_url(self):

        for point in self:

            point.maps_url = (
                "https://www.google.com/maps?q=%s,%s"
                % (
                    point.latitude,
                    point.longitude,
                )
            )

    # ==========================================================
    # GEOCODING SETTINGS
    # ==========================================================

    @api.model
    def _geocode_enabled(self):

        value = self.env[
            "ir.config_parameter"
        ].sudo().get_param(
            PARAM + "geocode_enabled",
            "1",
        )

        return str(value).lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    @api.model
    def _geocode_url(self):

        return (
            self.env[
                "ir.config_parameter"
            ].sudo().get_param(
                PARAM + "geocode_url"
            )
            or "https://nominatim.openstreetmap.org/reverse"
        ).strip()

    @api.model
    def _geocode_user_agent(self):

        return (
            self.env[
                "ir.config_parameter"
            ].sudo().get_param(
                PARAM + "geocode_user_agent"
            )
            or "FieldSalesperson/1.0"
        ).strip()

    # ==========================================================
    # FORMAT ADDRESS
    # ==========================================================

    @staticmethod
    def _format_address(data):
        """
        Convert Nominatim response into a short readable address.

        Example:

        Judge Farm, Heera Nagar, Haldwani, Nainital
        """

        address = data.get(
            "address"
        ) or {}

        groups = (
            (
                "road",
                "pedestrian",
                "footway",
                "neighbourhood",
            ),
            (
                "suburb",
                "city_district",
                "quarter",
                "neighbourhood",
            ),
            (
                "city",
                "town",
                "village",
                "municipality",
                "county",
            ),
            (
                "state_district",
            ),
            (
                "state",
            ),
        )

        parts = []

        for keys in groups:

            for key in keys:

                value = address.get(key)

                if (
                    value
                    and value not in parts
                ):
                    parts.append(value)
                    break

        label = ", ".join(
            parts[:4]
        )

        return (
            label
            or (
                data.get(
                    "display_name"
                )
                or ""
            )[:150]
            or False
        )

    # ==========================================================
    # FIND NEARBY EXISTING ADDRESS
    # ==========================================================

    def _find_nearby_address(self):
        """
        Reuse an address from a nearby location.

        Approximately 100 meters.
        """

        self.ensure_one()

        nearby = self.sudo().search(
            [
                ("id", "!=", self.id),
                ("address", "!=", False),

                (
                    "latitude",
                    ">=",
                    self.latitude - 0.001,
                ),

                (
                    "latitude",
                    "<=",
                    self.latitude + 0.001,
                ),

                (
                    "longitude",
                    ">=",
                    self.longitude - 0.001,
                ),

                (
                    "longitude",
                    "<=",
                    self.longitude + 0.001,
                ),
            ],
            order="id desc",
            limit=1,
        )

        return (
            nearby.address
            if nearby
            else False
        )

    # ==========================================================
    # REVERSE GEOCODE
    # ==========================================================

    def _reverse_geocode(self):
        """
        Reverse geocode one or MANY location points.

        This method intentionally supports recordsets.

        That is important because Today Tracking does:

            missing._reverse_geocode()

        where 'missing' can contain multiple points.
        """

        if not self:
            return False

        if not self._geocode_enabled():
            return False

        url = self._geocode_url()

        if not url:
            return False

        user_agent = (
            self._geocode_user_agent()
        )

        processed = False

        for point in self.sudo():

            # --------------------------------------------------
            # Already has address
            # --------------------------------------------------

            if point.address:
                continue

            # --------------------------------------------------
            # Try nearby known address first
            # --------------------------------------------------

            nearby_address = (
                point._find_nearby_address()
            )

            if nearby_address:

                point.write(
                    {
                        "address": nearby_address,
                        "geocode_tries": (
                            point.geocode_tries
                        ),
                    }
                )

                processed = True
                continue

            # --------------------------------------------------
            # Nominatim rate limit
            # --------------------------------------------------

            if processed:
                _time.sleep(1.1)

            # --------------------------------------------------
            # API request
            # --------------------------------------------------

            try:

                response = requests.get(
                    url,
                    params={
                        "format": "jsonv2",
                        "lat": point.latitude,
                        "lon": point.longitude,
                        "zoom": 17,
                        "addressdetails": 1,
                        "accept-language": "en",
                    },
                    headers={
                        "User-Agent": user_agent,
                    },
                    timeout=8,
                )

                response.raise_for_status()

                data = response.json()

                address = (
                    self._format_address(data)
                )

                if address:

                    point.write(
                        {
                            "address": address,
                            "geocode_tries": (
                                point.geocode_tries + 1
                            ),
                        }
                    )

                    processed = True

                else:

                    point.write(
                        {
                            "geocode_tries": (
                                point.geocode_tries + 1
                            ),
                        }
                    )

                    _logger.warning(
                        "geocoder returned no address "
                        "for point %s (%s, %s)",
                        point.id,
                        point.latitude,
                        point.longitude,
                    )

            except Exception as error:

                point.write(
                    {
                        "geocode_tries": (
                            point.geocode_tries + 1
                        ),
                    }
                )

                _logger.warning(
                    "address lookup failed for "
                    "point %s (%s, %s): %s",
                    point.id,
                    point.latitude,
                    point.longitude,
                    error,
                )

                # Do NOT stop the whole batch.
                # Continue with the next point.
                continue

        return True

    # ==========================================================
    # CRON - GEOCODE NEW POINTS
    # ==========================================================

    @api.model
    def _cron_geocode_points(self):
        """
        Fill addresses of newest locations.

        Maximum 15 points per cron execution.
        """

        if not self._geocode_enabled():
            return

        points = self.search(
            [
                ("address", "=", False),
                ("geocode_tries", "<", 3),
            ],
            order="timestamp desc, id desc",
            limit=15,
        )

        if not points:
            return

        points._reverse_geocode()

    # ==========================================================
    # COORDINATE VALIDATION
    # ==========================================================

    @api.constrains(
        "latitude",
        "longitude",
    )
    def _check_coordinates(self):

        for point in self:

            if not (
                -90.0
                <= point.latitude
                <= 90.0
            ):
                raise ValidationError(
                    "Latitude must be between -90 and 90."
                )

            if not (
                -180.0
                <= point.longitude
                <= 180.0
            ):
                raise ValidationError(
                    "Longitude must be between -180 and 180."
                )
