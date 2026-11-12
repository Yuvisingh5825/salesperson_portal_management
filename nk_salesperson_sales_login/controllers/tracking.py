# -*- coding: utf-8 -*-

import json
import math
from datetime import datetime, time, timedelta

import pytz
from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.http import request


PALETTE = [
    "#0d6efd",
    "#dc3545",
    "#198754",
    "#fd7e14",
    "#6f42c1",
    "#20c997",
    "#d63384",
    "#0dcaf0",
    "#795548",
    "#6c757d",
]


STATUS_LABEL = {
    "active": "Active",
    "no_signal": "No Signal",
    "offline": "Offline",
}


class NkTrackingController(http.Controller):

    # =========================================================
    # HELPERS
    # =========================================================

    def _employee(self):
        """Logged-in salesperson (portal session)."""

        employee_id = request.session.get(
            "nk_salesperson_employee_id"
        )

        Employee = request.env["hr.employee"]

        if not employee_id:
            return Employee

        return Employee.sudo().browse(
            employee_id
        ).exists()

    # ---------------------------------------------------------

    def _json(self, data, status=200):
        return request.make_json_response(
            data,
            status=status,
        )

    # ---------------------------------------------------------

    def _coords(self, kw):
        try:
            latitude = float(
                kw.get("latitude")
            )

            longitude = float(
                kw.get("longitude")
            )

            accuracy = float(
                kw.get("accuracy") or 0.0
            )

        except (TypeError, ValueError):
            return None

        if not (
            -90.0 <= latitude <= 90.0
            and
            -180.0 <= longitude <= 180.0
        ):
            return None

        return (
            latitude,
            longitude,
            max(accuracy, 0.0),
        )

    # ---------------------------------------------------------

    def _check_admin(self):

        user = request.env.user

        allowed = (
            user.has_group(
                "nk_salesperson_sales_login."
                "group_nk_salesperson_manager"
            )
            or user.has_group(
                "sales_team.group_sale_manager"
            )
            or user.has_group(
                "base.group_system"
            )
        )

        if not allowed:
            raise Forbidden()

    # ---------------------------------------------------------

    def _tz(self):
        """
        Display tracking times in Indian Standard Time
        when user's timezone is not configured.
        """

        try:
            return pytz.timezone(
                request.env.user.tz
                or "Asia/Kolkata"
            )

        except pytz.UnknownTimeZoneError:
            return pytz.timezone(
                "Asia/Kolkata"
            )

    # ---------------------------------------------------------

    def _local(
        self,
        value,
        fmt="%d-%b %I:%M %p",
    ):

        if not value:
            return ""

        return (
            pytz.utc
            .localize(value)
            .astimezone(self._tz())
            .strftime(fmt)
        )

    # ---------------------------------------------------------

    @staticmethod
    def _maps_url(
        latitude,
        longitude,
    ):

        return (
            "https://www.google.com/maps?q=%s,%s"
            % (
                latitude,
                longitude,
            )
        )

    # ---------------------------------------------------------

    @staticmethod
    def _distance_km(a, b):

        radius = 6371.0

        lat1, lng1, lat2, lng2 = map(
            math.radians,
            (
                a[0],
                a[1],
                b[0],
                b[1],
            ),
        )

        h = (
            math.sin(
                (lat2 - lat1) / 2
            ) ** 2
            +
            math.cos(lat1)
            * math.cos(lat2)
            * math.sin(
                (lng2 - lng1) / 2
            ) ** 2
        )

        return (
            2
            * radius
            * math.asin(
                math.sqrt(h)
            )
        )

    # ---------------------------------------------------------

    @staticmethod
    def _point_location_text(point):
        """
        Returns readable location information.

        Example:
            Judge Farm, Haldwani | 29.21830, 79.51300
        """

        if not point:
            return "-"

        address = (
            point.address
            or ""
        ).strip()

        coordinates = (
            "%.5f, %.5f"
            % (
                point.latitude,
                point.longitude,
            )
        )

        if address:
            return (
                "%s | %s"
                % (
                    address,
                    coordinates,
                )
            )

        return coordinates

    # =========================================================
    # SALESPERSON SIDE
    # START / PING / STOP
    # =========================================================

    @http.route(
        "/nk_salesperson/tracking/start",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
    )
    def tracking_start(self, **kw):

        employee = self._employee()

        if not employee:
            return self._json(
                {
                    "ok": False,
                    "error": "login",
                },
                401,
            )

        session = (
            request.env[
                "nk.tracking.session"
            ]
            .sudo()
            .start_for_employee(
                employee
            )
        )

        coords = self._coords(kw)

        if coords:
            session.add_point(
                *coords
            )

        return self._json(
            {
                "ok": True,
                "session_id": session.id,
            }
        )

    # ---------------------------------------------------------

    @http.route(
        "/nk_salesperson/tracking/ping",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
    )
    def tracking_ping(self, **kw):

        employee = self._employee()

        if not employee:
            return self._json(
                {
                    "ok": False,
                    "error": "login",
                },
                401,
            )

        session = (
            request.env[
                "nk.tracking.session"
            ]
            .sudo()
            .search(
                [
                    (
                        "employee_id",
                        "=",
                        employee.id,
                    ),
                    (
                        "state",
                        "=",
                        "active",
                    ),
                ],
                limit=1,
            )
        )

        if not session:
            return self._json(
                {
                    "ok": True,
                    "stopped": True,
                }
            )

        coords = self._coords(kw)

        if not coords:
            return self._json(
                {
                    "ok": False,
                    "error": "coordinates",
                },
                400,
            )

        point = session.add_point(
            *coords
        )

        return self._json(
            {
                "ok": True,
                "time": (
                    point.timestamp.isoformat()
                    + "Z"
                ),
                "accuracy": point.accuracy,
            }
        )

    # ---------------------------------------------------------

    @http.route(
        "/nk_salesperson/tracking/stop",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
    )
    def tracking_stop(self, **kw):

        employee = self._employee()

        if not employee:
            return self._json(
                {
                    "ok": False,
                    "error": "login",
                },
                401,
            )

        (
            request.env[
                "nk.tracking.session"
            ]
            .sudo()
            .search(
                [
                    (
                        "employee_id",
                        "=",
                        employee.id,
                    ),
                    (
                        "state",
                        "=",
                        "active",
                    ),
                ]
            )
            .action_stop()
        )

        return self._json(
            {
                "ok": True,
            }
        )

    # =========================================================
    # ADMIN SIDE
    # LIVE MAP
    # =========================================================

    @http.route(
        "/nk_salesperson/admin/tracking/map",
        type="http",
        auth="user",
        website=True,
        methods=["GET"],
    )
    def tracking_map(self, **kw):

        self._check_admin()

        return request.render(
            "nk_salesperson_sales_login."
            "nk_tracking_map_template",
            {},
        )

    # ---------------------------------------------------------

    @http.route(
        "/nk_salesperson/admin/tracking/live",
        type="http",
        auth="user",
        website=True,
        methods=["GET"],
    )
    def tracking_live(self, **kw):

        self._check_admin()

        employees = (
            request.env["hr.employee"]
            .sudo()
            .search(
                [
                    (
                        "nk_employee_id",
                        "!=",
                        False,
                    )
                ],
                order="name",
            )
        )

        Point = (
            request.env[
                "nk.location.point"
            ]
            .sudo()
        )

        missing = Point

        for employee in employees:

            last = Point.search(
                [
                    (
                        "employee_id",
                        "=",
                        employee.id,
                    )
                ],
                order="timestamp desc, id desc",
                limit=1,
            )

            if (
                last
                and not last.address
                and len(missing) < 2
            ):
                missing |= last

        if missing:
            missing._reverse_geocode()

        rows = []

        for employee in employees:

            has_location = bool(
                employee.nk_last_location_time
            )

            rows.append(
                {
                    "id": employee.id,
                    "name": employee.name,
                    "status": (
                        employee.nk_tracking_status
                    ),
                    "status_label": STATUS_LABEL.get(
                        employee.nk_tracking_status,
                        "",
                    ),
                    "lat": (
                        employee.nk_last_latitude
                        if has_location
                        else None
                    ),
                    "lng": (
                        employee.nk_last_longitude
                        if has_location
                        else None
                    ),
                    "accuracy": (
                        employee.nk_last_accuracy
                        if has_location
                        else None
                    ),
                    "last_time": self._local(
                        employee.nk_last_location_time
                    ),
                    "address": (
                        employee.nk_last_address
                        or ""
                    ),
                    "maps": (
                        self._maps_url(
                            employee.nk_last_latitude,
                            employee.nk_last_longitude,
                        )
                        if has_location
                        else ""
                    ),
                }
            )

        return self._json(
            {
                "employees": rows,
            }
        )

    # =========================================================
    # ADMIN SIDE
    # LOCATION HISTORY
    # =========================================================

    @http.route(
        "/nk_salesperson/admin/tracking/history",
        type="http",
        auth="user",
        website=True,
        methods=["GET"],
    )
    def tracking_history(
        self,
        employee_id=None,
        date=None,
        **kw
    ):

        self._check_admin()

        tz = self._tz()

        employees = (
            request.env["hr.employee"]
            .sudo()
            .search(
                [
                    (
                        "nk_employee_id",
                        "!=",
                        False,
                    )
                ],
                order="name",
            )
        )

        employee = (
            employees.filtered(
                lambda e:
                str(e.id)
                == str(employee_id)
            )[:1]
            or employees[:1]
        )

        try:

            day = datetime.strptime(
                date,
                "%Y-%m-%d",
            ).date()

        except (
            TypeError,
            ValueError,
        ):

            day = datetime.now(
                tz
            ).date()

        points = []

        total_km = 0.0

        if employee:

            start = (
                tz.localize(
                    datetime.combine(
                        day,
                        time.min,
                    )
                )
                .astimezone(
                    pytz.utc
                )
                .replace(
                    tzinfo=None
                )
            )

            end = (
                start
                + timedelta(days=1)
            )

            records = (
                request.env[
                    "nk.location.point"
                ]
                .sudo()
                .search(
                    [
                        (
                            "employee_id",
                            "=",
                            employee.id,
                        ),
                        (
                            "timestamp",
                            ">=",
                            start,
                        ),
                        (
                            "timestamp",
                            "<",
                            end,
                        ),
                    ],
                    order="timestamp asc, id asc",
                )
            )

            missing = records.filtered(
                lambda r:
                not r.address
            )

            if missing:
                try:
                    missing._reverse_geocode()
                except Exception:
                    pass

            previous = None

            for rec in records:

                current = (
                    rec.latitude,
                    rec.longitude,
                )

                if previous:

                    total_km += (
                        self._distance_km(
                            previous,
                            current,
                        )
                    )

                previous = current

                visit_label = ""

                if rec.visit_id:

                    visit_label = (
                        "%s - %s"
                        % (
                            rec.visit_id.name,
                            rec.visit_id.location,
                        )
                    )

                    quotations = (
                        rec.visit_id
                        .quotation_ids
                        .mapped("name")
                    )

                    if quotations:

                        visit_label += (
                            " (%s)"
                            % ", ".join(
                                quotations
                            )
                        )

                points.append(
                    {
                        "lat": rec.latitude,
                        "lng": rec.longitude,
                        "accuracy": rec.accuracy,

                        "time": self._local(
                            rec.timestamp,
                            "%I:%M %p",
                        ),

                        "address": (
                            rec.address
                            or ""
                        ),

                        "location": (
                            self._point_location_text(
                                rec
                            )
                        ),

                        "maps": self._maps_url(
                            rec.latitude,
                            rec.longitude,
                        ),

                        "visit": visit_label,
                    }
                )

        return request.render(
            "nk_salesperson_sales_login."
            "nk_tracking_history_template",
            {
                "employees": employees,
                "employee": employee,
                "day": day.strftime(
                    "%Y-%m-%d"
                ),
                "points": points,
                "points_json": json.dumps(
                    points
                ),
                "total_km": round(
                    total_km,
                    2,
                ),
            },
        )

    # =========================================================
    # ADMIN SIDE
    # TODAY TRACKING
    # =========================================================

    @http.route(
        "/nk_salesperson/admin/tracking/today",
        type="http",
        auth="user",
        website=True,
        methods=["GET"],
    )
    def tracking_today(
        self,
        employee_id=None,
        **kw
    ):

        self._check_admin()

        tz = self._tz()

        # -----------------------------------------------------
        # SALESPERSONS
        # -----------------------------------------------------

        employees = (
            request.env["hr.employee"]
            .sudo()
            .search(
                [
                    (
                        "nk_employee_id",
                        "!=",
                        False,
                    )
                ],
                order="name",
            )
        )

        # -----------------------------------------------------
        # SELECT EMPLOYEE
        # -----------------------------------------------------

        employee = (
            employees.filtered(
                lambda e:
                str(e.id)
                == str(employee_id)
            )[:1]
            or employees[:1]
        )

        # -----------------------------------------------------
        # TODAY
        # -----------------------------------------------------

        today = datetime.now(
            tz
        ).date()

        points = []

        total_km = 0.0

        first_point = None
        last_point = None

        first_time = "-"
        last_time = "-"

        first_location = "-"
        last_location = "-"

        tracking_active = False
        tracking_started = "-"

        # -----------------------------------------------------
        # TODAY'S DATA
        # -----------------------------------------------------

        if employee:

            # -------------------------------------------------
            # LOCAL MIDNIGHT -> UTC
            # -------------------------------------------------

            start = (
                tz.localize(
                    datetime.combine(
                        today,
                        time.min,
                    )
                )
                .astimezone(
                    pytz.utc
                )
                .replace(
                    tzinfo=None
                )
            )

            # Current UTC time
            end = datetime.utcnow()

            # -------------------------------------------------
            # LOCATION POINTS
            # -------------------------------------------------

            records = (
                request.env[
                    "nk.location.point"
                ]
                .sudo()
                .search(
                    [
                        (
                            "employee_id",
                            "=",
                            employee.id,
                        ),
                        (
                            "timestamp",
                            ">=",
                            start,
                        ),
                        (
                            "timestamp",
                            "<=",
                            end,
                        ),
                    ],
                    order="timestamp asc, id asc",
                )
            )

            # -------------------------------------------------
            # REVERSE GEOCODE
            # -------------------------------------------------

            missing = records.filtered(
                lambda r:
                not r.address
            )

            if missing:

                try:
                    missing._reverse_geocode()
                except Exception:
                    pass

            # -------------------------------------------------
            # DISTANCE
            # -------------------------------------------------

            previous = None

            for rec in records:

                current = (
                    rec.latitude,
                    rec.longitude,
                )

                if previous:

                    total_km += (
                        self._distance_km(
                            previous,
                            current,
                        )
                    )

                previous = current

                # ---------------------------------------------
                # VISIT
                # ---------------------------------------------

                visit_label = ""

                if rec.visit_id:

                    visit_label = (
                        "%s - %s"
                        % (
                            rec.visit_id.name,
                            rec.visit_id.location,
                        )
                    )

                    quotations = (
                        rec.visit_id
                        .quotation_ids
                        .mapped("name")
                    )

                    if quotations:

                        visit_label += (
                            " (%s)"
                            % ", ".join(
                                quotations
                            )
                        )

                # ---------------------------------------------
                # POINT
                # ---------------------------------------------

                points.append(
                    {
                        "lat": rec.latitude,
                        "lng": rec.longitude,
                        "accuracy": rec.accuracy,

                        "time": self._local(
                            rec.timestamp,
                            "%I:%M %p",
                        ),

                        "address": (
                            rec.address
                            or ""
                        ),

                        "location": (
                            self._point_location_text(
                                rec
                            )
                        ),

                        "maps": self._maps_url(
                            rec.latitude,
                            rec.longitude,
                        ),

                        "visit": visit_label,
                    }
                )

            # -------------------------------------------------
            # FIRST / LAST
            # -------------------------------------------------

            if records:

                first_point = records[0]
                last_point = records[-1]

                first_time = self._local(
                    first_point.timestamp,
                    "%I:%M %p",
                )

                last_time = self._local(
                    last_point.timestamp,
                    "%I:%M %p",
                )

                first_location = (
                    self._point_location_text(
                        first_point
                    )
                )

                last_location = (
                    self._point_location_text(
                        last_point
                    )
                )

                tracking_started = (
                    self._local(
                        first_point.timestamp,
                        "%I:%M %p",
                    )
                )

            # -------------------------------------------------
            # CURRENT STATUS
            # -------------------------------------------------

            tracking_active = (
                employee.nk_tracking_status
                == "active"
            )

        # -----------------------------------------------------
        # RENDER TODAY TRACKING
        # -----------------------------------------------------

        return request.render(
            "nk_salesperson_sales_login."
            "nk_tracking_today_template",
            {
                "employees": employees,

                "employee": employee,

                "day": today.strftime(
                    "%Y-%m-%d"
                ),

                "day_display": today.strftime(
                    "%d-%b-%Y"
                ),

                "points": points,

                "points_json": json.dumps(
                    points
                ),

                "total_km": round(
                    total_km,
                    2,
                ),

                "location_count": len(
                    points
                ),

                "first_time": first_time,

                "first_location": first_location,

                "last_time": last_time,

                "last_location": last_location,

                "tracking_active": tracking_active,

                "tracking_status": (
                    STATUS_LABEL.get(
                        employee.nk_tracking_status,
                        "Offline",
                    )
                    if employee
                    else "Offline"
                ),

                "tracking_started": tracking_started,
            },
        )

    # =========================================================
    # ADMIN SIDE
    # REPORT
    # =========================================================

    @staticmethod
    def _parse_date(
        value,
        default,
    ):

        try:

            return datetime.strptime(
                value,
                "%Y-%m-%d",
            ).date()

        except (
            TypeError,
            ValueError,
        ):

            return default

    # ---------------------------------------------------------

    @http.route(
        "/nk_salesperson/admin/tracking/report",
        type="http",
        auth="user",
        website=True,
        methods=["GET"],
    )
    def tracking_report(
        self,
        employee_ids=None,
        date_from=None,
        date_to=None,
        **kw
    ):

        self._check_admin()

        tz = self._tz()

        # -----------------------------------------------------
        # Employees
        # -----------------------------------------------------

        all_employees = (
            request.env["hr.employee"]
            .sudo()
            .search(
                [
                    (
                        "nk_employee_id",
                        "!=",
                        False,
                    )
                ],
                order="name",
            )
        )

        if (
            employee_ids
            and employee_ids != "all"
        ):

            wanted = [
                int(x)
                for x in employee_ids.split(",")
                if x.strip().isdigit()
            ]

            employees = (
                all_employees.filtered(
                    lambda e:
                    e.id in wanted
                )
            )

        else:

            employees = all_employees

        # -----------------------------------------------------
        # Dates
        # -----------------------------------------------------

        today = datetime.now(
            tz
        ).date()

        d_from = self._parse_date(
            date_from,
            today,
        )

        d_to = self._parse_date(
            date_to,
            d_from,
        )

        if d_to < d_from:

            d_from, d_to = (
                d_to,
                d_from,
            )

        # -----------------------------------------------------
        # Maximum 7 days
        # -----------------------------------------------------

        note = ""

        if (
            d_to - d_from
        ).days > 6:

            d_to = (
                d_from
                + timedelta(days=6)
            )

            note = (
                "Map shows maximum 7 days "
                "at a time. Showing %s to %s."
                % (
                    d_from,
                    d_to,
                )
            )

        # -----------------------------------------------------
        # Local -> UTC
        # -----------------------------------------------------

        start = (
            tz.localize(
                datetime.combine(
                    d_from,
                    time.min,
                )
            )
            .astimezone(
                pytz.utc
            )
            .replace(
                tzinfo=None
            )
        )

        end = (
            tz.localize(
                datetime.combine(
                    d_to
                    + timedelta(days=1),
                    time.min,
                )
            )
            .astimezone(
                pytz.utc
            )
            .replace(
                tzinfo=None
            )
        )

        # -----------------------------------------------------
        # Tracking records
        # -----------------------------------------------------

        records = (
            request.env[
                "nk.location.point"
            ]
            .sudo()
            .search(
                [
                    (
                        "employee_id",
                        "in",
                        employees.ids,
                    ),
                    (
                        "timestamp",
                        ">=",
                        start,
                    ),
                    (
                        "timestamp",
                        "<",
                        end,
                    ),
                ],
                order="timestamp asc, id asc",
            )
        )

        # -----------------------------------------------------
        # Reverse geocode first/last locations
        # -----------------------------------------------------

        first_last_points = (
            request.env[
                "nk.location.point"
            ]
            .sudo()
            .browse()
        )

        for emp in employees:

            emp_records = records.filtered(
                lambda r:
                r.employee_id.id
                == emp.id
            )

            if emp_records:

                first_last_points |= (
                    emp_records[0]
                )

                if len(emp_records) > 1:

                    first_last_points |= (
                        emp_records[-1]
                    )

        missing_location = (
            first_last_points.filtered(
                lambda r:
                not r.address
            )
        )

        if missing_location:

            try:
                missing_location._reverse_geocode()
            except Exception:
                pass

        # -----------------------------------------------------
        # Group records
        # -----------------------------------------------------

        by_employee = {
            emp.id: []
            for emp in employees
        }

        for rec in records:

            by_employee[
                rec.employee_id.id
            ].append(rec)

        # -----------------------------------------------------
        # Summary + map points
        # -----------------------------------------------------

        summary = []

        points = []

        for index, emp in enumerate(
            employees
        ):

            color = PALETTE[
                index
                % len(PALETTE)
            ]

            rows = by_employee[
                emp.id
            ]

            # -------------------------------------------------
            # Distance
            # -------------------------------------------------

            km = 0.0

            previous = None
            previous_day = None

            for rec in rows:

                local = (
                    pytz.utc
                    .localize(
                        rec.timestamp
                    )
                    .astimezone(
                        tz
                    )
                )

                day = local.strftime(
                    "%Y-%m-%d"
                )

                current = (
                    rec.latitude,
                    rec.longitude,
                )

                if (
                    previous
                    and day == previous_day
                ):

                    km += (
                        self._distance_km(
                            previous,
                            current,
                        )
                    )

                previous = current
                previous_day = day

                # -------------------------------------------------
                # Visit
                # -------------------------------------------------

                visit_label = ""

                if rec.visit_id:

                    visit_label = (
                        "%s - %s"
                        % (
                            rec.visit_id.name,
                            rec.visit_id.location,
                        )
                    )

                    quotations = (
                        rec.visit_id
                        .quotation_ids
                        .mapped("name")
                    )

                    if quotations:

                        visit_label += (
                            " (%s)"
                            % ", ".join(
                                quotations
                            )
                        )

                # -------------------------------------------------
                # Map point
                # -------------------------------------------------

                points.append(
                    {
                        "emp": emp.name,
                        "color": color,
                        "day": day,

                        "time": local.strftime(
                            "%d-%b %I:%M %p"
                        ),

                        "lat": rec.latitude,
                        "lng": rec.longitude,
                        "accuracy": rec.accuracy,

                        "address": (
                            rec.address
                            or ""
                        ),

                        "location": (
                            self._point_location_text(
                                rec
                            )
                        ),

                        "maps": self._maps_url(
                            rec.latitude,
                            rec.longitude,
                        ),

                        "visit": visit_label,
                    }
                )

            # -------------------------------------------------
            # First / Last
            # -------------------------------------------------

            if rows:

                first_point = rows[0]
                last_point = rows[-1]

                first_time = self._local(
                    first_point.timestamp
                )

                last_time = self._local(
                    last_point.timestamp
                )

                first_location = (
                    self._point_location_text(
                        first_point
                    )
                )

                last_location = (
                    self._point_location_text(
                        last_point
                    )
                )

                first_display = (
                    "%s | %s"
                    % (
                        first_time,
                        first_location,
                    )
                )

                last_display = (
                    "%s | %s"
                    % (
                        last_time,
                        last_location,
                    )
                )

            else:

                first_point = None
                last_point = None

                first_display = "-"
                last_display = "-"

            # -------------------------------------------------
            # Summary
            # -------------------------------------------------

            summary.append(
                {
                    "name": emp.name,

                    "color": color,

                    "status": STATUS_LABEL.get(
                        emp.nk_tracking_status,
                        "",
                    ),

                    "sessions": len(
                        set(
                            r.session_id.id
                            for r in rows
                            if r.session_id
                        )
                    ),

                    "points": len(rows),

                    "km": round(
                        km,
                        2,
                    ),

                    "first": first_display,

                    "last": last_display,

                    "first_time": (
                        self._local(
                            first_point.timestamp
                        )
                        if rows
                        else "-"
                    ),

                    "first_location": (
                        self._point_location_text(
                            first_point
                        )
                        if rows
                        else "-"
                    ),

                    "last_time": (
                        self._local(
                            last_point.timestamp
                        )
                        if rows
                        else "-"
                    ),

                    "last_location": (
                        self._point_location_text(
                            last_point
                        )
                        if rows
                        else "-"
                    ),
                }
            )

        # -----------------------------------------------------
        # Render report
        # -----------------------------------------------------

        return request.render(
            "nk_salesperson_sales_login."
            "nk_tracking_report_template",
            {
                "summary": summary,

                "points": points,

                "points_json": json.dumps(
                    points
                ),

                "date_from": str(
                    d_from
                ),

                "date_to": str(
                    d_to
                ),

                "note": note,
            },
        )
