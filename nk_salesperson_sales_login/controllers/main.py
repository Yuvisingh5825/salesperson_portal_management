# -*- coding: utf-8 -*-

import base64
from urllib.parse import quote

import pytz

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request
from werkzeug.exceptions import NotFound


def _local_datetime(value, tz_name=None):
    """Database time (UTC) -> local time text, e.g. 16-Oct-2026 01:07 PM.

    Time zone: system parameter nk_salesperson.timezone
    (default Asia/Kolkata).
    """
    if not value:
        return ""
    try:
        tz = pytz.timezone(tz_name or "Asia/Kolkata")
    except pytz.UnknownTimeZoneError:
        tz = pytz.timezone("Asia/Kolkata")
    return (
        pytz.utc.localize(value)
        .astimezone(tz)
        .strftime("%d-%b-%Y %I:%M %p")
    )


class NkSalespersonController(http.Controller):

    # =========================================================
    # HELPERS
    # =========================================================

    def _get_employee(self):
        """Logged-in salesperson."""
        Employee = request.env["hr.employee"]
        employee_id = request.session.get(
            "nk_salesperson_employee_id"
        )

        if not employee_id:
            return Employee

        employee = (
            Employee.sudo()
            .browse(employee_id)
            .exists()
        )

        if not employee:
            request.session.pop(
                "nk_salesperson_employee_id",
                None,
            )
            request.session.pop(
                "nk_salesperson_employee_name",
                None,
            )
            return Employee

        return employee

    def _redirect(
        self,
        message,
        kind="error",
        path="/nk_salesperson",
    ):
        """Redirect with success/error message."""
        return request.redirect(
            "%s?%s=%s"
            % (
                path,
                kind,
                quote(message),
            )
        )

    def _get_own_order(self, employee, order_id):
        return (
            request.env["sale.order"]
            .sudo()
            .search(
                [
                    ("id", "=", order_id),
                    ("nk_employee_id", "=", employee.id),
                ],
                limit=1,
            )
        )

    # =========================================================
    # EXPENSE HELPERS
    # =========================================================

    def _get_expense_amount(self, expense):
        return expense.total_expense or 0.0

    def _get_expense_type(self, expense):
        """
        Returns the main expense type for backward compatibility.
        If multiple types are present, the first available type
        is returned.
        """

        if expense.travel_amount:
            return "travel"

        if expense.food_amount:
            return "food"

        if expense.hotel_amount:
            return "hotel"

        if expense.fuel_amount:
            return "fuel"

        if expense.mobile_amount:
            return "mobile"

        if expense.other_amount:
            return "other"

        return "other"

    def _expense_totals(self, expenses):
        """
        Calculate expense totals from the main
        nk.salesperson.expense model.
        """

        return {
            "total_expense": sum(
                expenses.mapped("total_expense")
            ),

            "submitted_expense": sum(
                expenses.filtered(
                    lambda e: e.state == "submitted"
                ).mapped("total_expense")
            ),

            "approved_expense": sum(
                expenses.filtered(
                    lambda e: e.state == "approved"
                ).mapped("total_expense")
            ),

            "rejected_expense": sum(
                expenses.filtered(
                    lambda e: e.state == "rejected"
                ).mapped("total_expense")
            ),

            # Individual expense categories
            "travel_expense": sum(
                expenses.mapped("travel_amount")
            ),

            "food_expense": sum(
                expenses.mapped("food_amount")
            ),

            "hotel_expense": sum(
                expenses.mapped("hotel_amount")
            ),

            "fuel_expense": sum(
                expenses.mapped("fuel_amount")
            ),

            "mobile_expense": sum(
                expenses.mapped("mobile_amount")
            ),

            "other_expense": sum(
                expenses.mapped("other_amount")
            ),
        }

    def _get_own_expense(self, employee, expense_id):
        return (
            request.env["nk.salesperson.expense"]
            .sudo()
            .search(
                [
                    ("id", "=", expense_id),
                    ("employee_id", "=", employee.id),
                ],
                limit=1,
            )
        )

    def _get_partner_options(self, employee):
        """
        Customers the salesperson can select:
        all customers + customers from own quotations.
        """

        Partner = request.env["res.partner"].sudo()

        own_partner_ids = (
            request.env["sale.order"]
            .sudo()
            .search(
                [
                    ("nk_employee_id", "=", employee.id)
                ]
            )
            .mapped("partner_id")
            .ids
        )

        domain = [
            ("active", "=", True)
        ]

        if "customer_rank" in Partner._fields:
            domain += [
                "|",
                ("customer_rank", ">", 0),
                ("id", "in", own_partner_ids),
            ]
        else:
            domain += [
                ("id", "in", own_partner_ids)
            ]

        return Partner.search(
            domain,
            order="name",
            limit=300,
        )

    def _get_posted_ids(self, field_name):
        """
        Read checkbox/multiple-select values from POST.
        """

        ids = []

        for value in request.httprequest.form.getlist(
            field_name
        ):
            try:
                ids.append(int(value))
            except (
                TypeError,
                ValueError,
            ):
                continue

        return list(dict.fromkeys(ids))

    # =========================================================
    # EXPENSE FORM VALIDATION
    # =========================================================

    def _validate_expense_form(
        self,
        employee,
        expense_date,
        location,
        description,
        travel_amount,
        food_amount,
        hotel_amount,
        fuel_amount,
        mobile_amount,
        other_amount,
    ):
        """
        Validate expense form.

        One expense record can contain multiple expense types.
        There is NO expense line model.
        """

        if not expense_date:
            return (
                "Expense date is required.",
                None,
            )

        if not location or not location.strip():
            return (
                "Location is required.",
                None,
            )

        if not description or not description.strip():
            return (
                "Description is required.",
                None,
            )

        # -----------------------------------------------------
        # Convert amounts
        # -----------------------------------------------------

        amount_values = {}

        raw_amounts = {
            "travel_amount": travel_amount,
            "food_amount": food_amount,
            "hotel_amount": hotel_amount,
            "fuel_amount": fuel_amount,
            "mobile_amount": mobile_amount,
            "other_amount": other_amount,
        }

        for field_name, value in raw_amounts.items():

            try:
                amount = float(value or 0)
            except (
                TypeError,
                ValueError,
            ):
                return (
                    "Please enter a valid amount.",
                    None,
                )

            if amount < 0:
                return (
                    "Expense amount cannot be negative.",
                    None,
                )

            amount_values[field_name] = amount

        # -----------------------------------------------------
        # At least one expense
        # -----------------------------------------------------

        total_amount = sum(
            amount_values.values()
        )

        if total_amount <= 0:
            return (
                "Please enter at least one expense amount.",
                None,
            )

        # -----------------------------------------------------
        # GPS (optional, filled by "Use my current location")
        # -----------------------------------------------------

        params = request.params

        try:
            latitude = float(params.get("latitude") or 0)
            longitude = float(params.get("longitude") or 0)
        except (TypeError, ValueError):
            latitude = 0.0
            longitude = 0.0

        if not (
            -90.0 <= latitude <= 90.0
            and -180.0 <= longitude <= 180.0
        ):
            latitude = 0.0
            longitude = 0.0

        address = (params.get("address") or "").strip()[:250]

        # -----------------------------------------------------
        # VALUES FOR nk.salesperson.expense
        # -----------------------------------------------------

        vals = {
            "expense_date": expense_date,

            "location": location.strip(),

            "description": description.strip(),

            "travel_amount": amount_values[
                "travel_amount"
            ],

            "food_amount": amount_values[
                "food_amount"
            ],

            "hotel_amount": amount_values[
                "hotel_amount"
            ],

            "fuel_amount": amount_values[
                "fuel_amount"
            ],

            "mobile_amount": amount_values[
                "mobile_amount"
            ],

            "other_amount": amount_values[
                "other_amount"
            ],
        }

        # Only overwrite GPS / address when the salesperson sent them
        if latitude or longitude:
            vals["latitude"] = latitude
            vals["longitude"] = longitude

        if address:
            vals["address"] = address

        return None, vals

    # =========================================================
    # LOGIN
    # =========================================================

    @http.route(
        "/nk_salesperson/login",
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
    )
    def login_page(
        self,
        error=None,
        **kw
    ):

        if self._get_employee():
            return request.redirect(
                "/nk_salesperson"
            )

        return request.render(
            "nk_salesperson_sales_login.nk_login_template",
            {
                "error": error
            },
        )

    @http.route(
        "/nk_salesperson/login/submit",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def login_submit(
        self,
        nk_employee_id=None,
        password=None,
        **kw
    ):

        employee_id = (
            nk_employee_id or ""
        ).strip()

        entered_password = password or ""

        employee = (
            request.env["hr.employee"]
            .sudo()
            .search(
                [
                    (
                        "nk_employee_id",
                        "=",
                        employee_id,
                    ),
                    (
                        "active",
                        "=",
                        True,
                    ),
                ],
                limit=1,
            )
        )

        if not employee:
            return request.render(
                "nk_salesperson_sales_login.nk_login_template",
                {
                    "error": "Employee ID not found.",
                    "nk_employee_id": employee_id,
                },
            )

        if employee.nk_password != entered_password:
            return request.render(
                "nk_salesperson_sales_login.nk_login_template",
                {
                    "error": "Invalid Password.",
                    "nk_employee_id": employee_id,
                },
            )

        request.session[
            "nk_salesperson_employee_id"
        ] = employee.id

        request.session[
            "nk_salesperson_employee_name"
        ] = employee.name

        return request.redirect(
            "/nk_salesperson"
        )

    @http.route(
        "/nk_salesperson/logout",
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
    )
    def logout(self, **kw):

        request.session.pop(
            "nk_salesperson_employee_id",
            None,
        )

        request.session.pop(
            "nk_salesperson_employee_name",
            None,
        )

        return request.redirect(
            "/nk_salesperson/login"
        )

    # =========================================================
    # DASHBOARD
    # =========================================================

    @http.route(
        "/nk_salesperson",
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
    )
    def dashboard(
        self,
        success=None,
        error=None,
        **kw
    ):

        employee = self._get_employee()

        if not employee:
            return request.redirect(
                "/nk_salesperson/login"
            )

        Order = (
            request.env["sale.order"]
            .sudo()
        )

        # Open quotations
        orders = Order.search(
            [
                (
                    "nk_employee_id",
                    "=",
                    employee.id,
                ),
                (
                    "state",
                    "in",
                    [
                        "draft",
                        "sent",
                    ],
                ),
            ],
            order="create_date desc",
        )

        # All quotations/orders
        all_orders = Order.search(
            [
                (
                    "nk_employee_id",
                    "=",
                    employee.id,
                )
            ],
            order="create_date desc",
        )

        # Expenses
        expenses = (
            request.env[
                "nk.salesperson.expense"
            ]
            .sudo()
            .search(
                [
                    (
                        "employee_id",
                        "=",
                        employee.id,
                    )
                ],
                order="expense_date desc, id desc",
                limit=20,
            )
        )

        values = {
            "employee": employee,
            "orders": orders,
            "all_orders": all_orders,
            "partners": self._get_partner_options(
                employee
            ),
            "expenses": expenses,
            "success": success,
            "error": error,
        }

        values.update(
            self._expense_totals(
                expenses
            )
        )

        Survey = request.env["ionex.survey"].sudo()
        survey_domain = [("employee_id", "=", employee.id)]
        values["surveys"] = Survey.search(
            survey_domain,
            order="survey_date desc, id desc",
            limit=10,
        )
        values["survey_total"] = Survey.search_count(survey_domain)
        values["type_labels"] = dict(Survey._fields["survey_type"].selection)
        values["state_labels"] = dict(Survey._fields["state"].selection)

        TrackingSession = request.env["nk.tracking.session"].sudo()
        values["tracking_session"] = TrackingSession.search([
            ("employee_id", "=", employee.id),
            ("state", "=", "active"),
        ], limit=1)
        values["tracking_interval"] = TrackingSession._interval_seconds()

        tz_name = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("nk_salesperson.timezone")
        )
        values["nk_dt"] = lambda value: _local_datetime(value, tz_name)

        return request.render(
            "nk_salesperson_sales_login.nk_dashboard_template",
            values,
        )

    # =========================================================
    # CREATE EXPENSE
    # =========================================================

    @http.route(
        "/nk_salesperson/expense/create",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def create_expense(
        self,
        expense_date=None,
        location=None,
        description=None,
        travel_amount=None,
        food_amount=None,
        hotel_amount=None,
        fuel_amount=None,
        mobile_amount=None,
        other_amount=None,
        **kw
    ):

        employee = self._get_employee()

        if not employee:
            return request.redirect(
                "/nk_salesperson/login"
            )

        # -----------------------------------------------------
        # VALIDATE
        # -----------------------------------------------------

        error, data = (
            self._validate_expense_form(
                employee,
                expense_date,
                location,
                description,
                travel_amount,
                food_amount,
                hotel_amount,
                fuel_amount,
                mobile_amount,
                other_amount,
            )
        )

        if error:
            return self._redirect(
                error
            )

        # -----------------------------------------------------
        # RECEIPT
        # -----------------------------------------------------

        receipt = (
            request.httprequest.files.get(
                "receipt"
            )
        )

        receipt_data = False
        receipt_filename = False

        if (
            receipt
            and receipt.filename
        ):
            receipt_data = (
                base64.b64encode(
                    receipt.read()
                )
            )

            receipt_filename = (
                receipt.filename
            )

        # -----------------------------------------------------
        # CREATE ONE EXPENSE RECORD
        # -----------------------------------------------------

        vals = dict(data)

        vals.update(
            {
                "employee_id": employee.id,

                "state": "submitted",

                "company_id": request.env.company.id,

                "currency_id": (
                    request.env.company
                    .currency_id.id
                ),

                "receipt": receipt_data,

                "receipt_filename": (
                    receipt_filename
                ),
            }
        )

        request.env[
            "nk.salesperson.expense"
        ].sudo().create(vals)

        return self._redirect(
            "Expense submitted successfully.",
            "success",
        )

    # =========================================================
    # EXPENSE : PLACE NAME FROM GPS
    # =========================================================

    @http.route(
        "/nk_salesperson/expense/place",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def expense_place(
        self,
        latitude=None,
        longitude=None,
        **kw
    ):

        employee = self._get_employee()

        if not employee:
            return request.make_json_response(
                {"ok": False, "error": "login"},
                status=401,
            )

        try:
            lat = float(latitude)
            lng = float(longitude)
        except (TypeError, ValueError):
            return request.make_json_response(
                {"ok": False, "error": "coordinates"},
                status=400,
            )

        if not (
            -90.0 <= lat <= 90.0
            and -180.0 <= lng <= 180.0
        ):
            return request.make_json_response(
                {"ok": False, "error": "coordinates"},
                status=400,
            )

        place, address = (
            request.env["nk.salesperson.expense"]
            .sudo()
            .nk_lookup_place(lat, lng)
        )

        return request.make_json_response(
            {
                "ok": True,
                "place": place,
                "address": address,
            }
        )

    # =========================================================
    # EDIT EXPENSE
    # =========================================================

    @http.route(
        "/nk_salesperson/expense/<int:expense_id>/edit",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def edit_expense(
        self,
        expense_id,
        expense_date=None,
        location=None,
        description=None,
        travel_amount=None,
        food_amount=None,
        hotel_amount=None,
        fuel_amount=None,
        mobile_amount=None,
        other_amount=None,
        **kw
    ):

        employee = self._get_employee()

        if not employee:
            return request.redirect(
                "/nk_salesperson/login"
            )

        expense = self._get_own_expense(
            employee,
            expense_id,
        )

        if not expense:
            return self._redirect(
                "Expense not found."
            )

        if expense.state == "approved":
            return self._redirect(
                "Approved expense cannot be edited."
            )

        # -----------------------------------------------------
        # VALIDATE
        # -----------------------------------------------------

        error, data = (
            self._validate_expense_form(
                employee,
                expense_date,
                location,
                description,
                travel_amount,
                food_amount,
                hotel_amount,
                fuel_amount,
                mobile_amount,
                other_amount,
            )
        )

        if error:
            return self._redirect(
                error
            )

        vals = dict(data)

        # Edited expense goes back for approval
        vals["state"] = "submitted"

        vals["rejection_reason"] = False

        # -----------------------------------------------------
        # NEW RECEIPT
        # -----------------------------------------------------

        receipt = (
            request.httprequest.files.get(
                "receipt"
            )
        )

        if (
            receipt
            and receipt.filename
        ):
            vals["receipt"] = (
                base64.b64encode(
                    receipt.read()
                )
            )

            vals["receipt_filename"] = (
                receipt.filename
            )

        expense.write(vals)

        return self._redirect(
            "Expense updated successfully.",
            "success",
        )

    # =========================================================
    # DELETE EXPENSE
    # =========================================================

    @http.route(
        "/nk_salesperson/expense/<int:expense_id>/delete",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def delete_expense(
        self,
        expense_id,
        **kw
    ):

        employee = self._get_employee()

        if not employee:
            return request.redirect(
                "/nk_salesperson/login"
            )

        expense = self._get_own_expense(
            employee,
            expense_id,
        )

        if not expense:
            return self._redirect(
                "Expense not found."
            )

        if expense.state == "approved":
            return self._redirect(
                "Approved expense cannot be deleted."
            )

        expense.unlink()

        return self._redirect(
            "Expense deleted successfully.",
            "success",
        )

    # =========================================================
    # EDIT QUOTATION - PAGE
    # =========================================================

    @http.route(
        "/nk_salesperson/quotation/<int:order_id>/edit",
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
    )
    def edit_quotation_page(
        self,
        order_id,
        error=None,
        **kw
    ):

        employee = self._get_employee()

        if not employee:
            return request.redirect(
                "/nk_salesperson/login"
            )

        order = self._get_own_order(
            employee,
            order_id,
        )

        if not order:
            raise NotFound()

        if order.state not in (
            "draft",
            "sent",
        ):
            return self._redirect(
                "Only draft or sent quotations can be edited."
            )

        # Edit opens the same default Odoo quotation form
        # that "New Quotation > Normal Quotation" opens.
        return request.redirect(
            "/web#id=%s&model=sale.order&view_type=form" % order.id
        )

        lines = order.order_line.filtered(
            lambda l: not l.display_type
        )

        products = (
            request.env[
                "product.product"
            ]
            .sudo()
            .search(
                [
                    (
                        "sale_ok",
                        "=",
                        True,
                    )
                ],
                order="name",
                limit=500,
            )
        ) | lines.mapped(
            "product_id"
        )

        partners = (
            self._get_partner_options(
                employee
            )
            | order.partner_id
        )

        return request.render(
            "nk_salesperson_sales_login.nk_quotation_edit_template",
            {
                "employee": employee,
                "order": order,
                "lines": lines,
                "products": products,
                "partners": partners,
                "error": error,
            },
        )

    # =========================================================
    # EDIT QUOTATION - SAVE
    # =========================================================

    @http.route(
        "/nk_salesperson/quotation/<int:order_id>/edit/submit",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def edit_quotation_submit(
        self,
        order_id,
        partner_id=None,
        **kw
    ):

        employee = self._get_employee()

        if not employee:
            return request.redirect(
                "/nk_salesperson/login"
            )

        order = self._get_own_order(
            employee,
            order_id,
        )

        if not order:
            return self._redirect(
                "Quotation not found."
            )

        if order.state not in (
            "draft",
            "sent",
        ):
            return self._redirect(
                "Only draft or sent quotations can be edited."
            )

        edit_path = (
            "/nk_salesperson/quotation/%s/edit"
            % order.id
        )

        # -----------------------------------------------------
        # CUSTOMER
        # -----------------------------------------------------

        try:
            partner_id = int(
                partner_id
            )
        except (
            TypeError,
            ValueError,
        ):
            return self._redirect(
                "Please select a customer.",
                "error",
                edit_path,
            )

        allowed_partners = (
            self._get_partner_options(
                employee
            )
            | order.partner_id
        )

        if partner_id not in (
            allowed_partners.ids
        ):
            return self._redirect(
                "Invalid customer selected.",
                "error",
                edit_path,
            )

        # -----------------------------------------------------
        # PRODUCT LINES
        # -----------------------------------------------------

        form = request.httprequest.form

        line_ids = form.getlist(
            "line_id"
        )

        product_ids = form.getlist(
            "product_id"
        )

        qtys = form.getlist(
            "qty"
        )

        prices = form.getlist(
            "price"
        )

        if not (
            len(line_ids)
            == len(product_ids)
            == len(qtys)
            == len(prices)
        ):
            return self._redirect(
                "Invalid form data.",
                "error",
                edit_path,
            )

        existing = {
            line.id: line
            for line in order.order_line.filtered(
                lambda l: not l.display_type
            )
        }

        Product = (
            request.env[
                "product.product"
            ].sudo()
        )

        commands = []

        kept = 0

        for (
            line_id_s,
            product_id_s,
            qty_s,
            price_s,
        ) in zip(
            line_ids,
            product_ids,
            qtys,
            prices,
        ):

            line_id_s = (
                line_id_s or ""
            ).strip()

            product_id_s = (
                product_id_s or ""
            ).strip()

            try:
                line_id = (
                    int(line_id_s)
                    if line_id_s
                    else 0
                )
            except ValueError:
                return self._redirect(
                    "Invalid line.",
                    "error",
                    edit_path,
                )

            if (
                line_id
                and line_id not in existing
            ):
                return self._redirect(
                    "Invalid line.",
                    "error",
                    edit_path,
                )

            # No product = remove/ignore
            if not product_id_s:

                if line_id:
                    commands.append(
                        (2, line_id)
                    )

                continue

            try:
                product_id = int(
                    product_id_s
                )

                qty = float(
                    qty_s or 0
                )

            except ValueError:
                return self._redirect(
                    "Invalid product or quantity.",
                    "error",
                    edit_path,
                )

            if qty <= 0:
                return self._redirect(
                    "Quantity must be greater than zero.",
                    "error",
                    edit_path,
                )

            product = (
                Product
                .browse(product_id)
                .exists()
            )

            if not product:
                return self._redirect(
                    "Invalid product.",
                    "error",
                    edit_path,
                )

            if not product.sale_ok and not (
                line_id
                and existing[
                    line_id
                ].product_id == product
            ):
                return self._redirect(
                    "%s cannot be sold."
                    % product.display_name,
                    "error",
                    edit_path,
                )

            vals = {
                "product_id": product.id,
                "product_uom_qty": qty,
            }

            price_s = (
                price_s or ""
            ).strip()

            if price_s:

                try:
                    price = float(
                        price_s
                    )
                except ValueError:
                    return self._redirect(
                        "Invalid price.",
                        "error",
                        edit_path,
                    )

                if price < 0:
                    return self._redirect(
                        "Price cannot be negative.",
                        "error",
                        edit_path,
                    )

                vals[
                    "price_unit"
                ] = price

            if line_id:
                commands.append(
                    (
                        1,
                        line_id,
                        vals,
                    )
                )
            else:
                commands.append(
                    (
                        0,
                        0,
                        vals,
                    )
                )

            kept += 1

        if not kept:
            return self._redirect(
                "A quotation needs at least one product line.",
                "error",
                edit_path,
            )

        order.write(
            {
                "partner_id": partner_id,
                "order_line": commands,
            }
        )

        return self._redirect(
            "Quotation updated successfully.",
            "success",
            "/nk_salesperson/quotation/%s" % order.id,
        )

    # =========================================================
    # NEW QUOTATION
    # =========================================================

    @http.route(
        "/nk_salesperson/quotation/new",
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
    )
    def new_quotation(
        self,
        **kw
    ):

        if not self._get_employee():
            return request.redirect(
                "/nk_salesperson/login"
            )

        return request.render(
            "nk_salesperson_sales_login.ionex_quotation_choice_template",
            {
                "employee": self._get_employee(),
            },
        )

    # =========================================================
    # QUOTATION DETAIL
    # =========================================================

    @http.route(
        "/nk_salesperson/quotation/<int:order_id>",
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
    )
    def quotation_detail(
        self,
        order_id,
        success=None,
        error=None,
        **kw
    ):

        employee = self._get_employee()

        if not employee:
            return request.redirect(
                "/nk_salesperson/login"
            )

        order = (
            request.env["sale.order"]
            .sudo()
            .search(
                [
                    (
                        "id",
                        "=",
                        order_id,
                    ),
                    (
                        "nk_employee_id",
                        "=",
                        employee.id,
                    ),
                ],
                limit=1,
            )
        )

        if not order:
            raise NotFound()

        return request.render(
            "nk_salesperson_sales_login.nk_quotation_detail_template",
            {
                "employee": employee,
                "order": order,
                "success": success,
                "error": error,
            },
        )

    # =========================================================
    # REJECT QUOTATION
    # =========================================================

    @http.route(
        "/nk_salesperson/quotation/<int:order_id>/reject",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
    )
    def reject_quotation(
        self,
        order_id,
        reject_reason=None,
        **kw
    ):

        employee = self._get_employee()

        if not employee:
            return request.redirect(
                "/nk_salesperson/login"
            )

        order = self._get_own_order(employee, order_id)

        if not order:
            raise NotFound()

        try:
            order.nk_reject_quotation(reject_reason)
        except UserError as e:
            return self._redirect(str(e.args[0]))

        return self._redirect(
            "Quotation %s rejected." % order.name,
            kind="success",
        )

    # =========================================================
    # REPORTING
    # =========================================================

    @http.route(
        "/nk_salesperson/reporting",
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
    )
    def reporting(
        self,
        **kw
    ):

        employee = self._get_employee()

        if not employee:
            return request.redirect(
                "/nk_salesperson/login"
            )

        orders = (
            request.env["sale.order"]
            .sudo()
            .search(
                [
                    (
                        "nk_employee_id",
                        "=",
                        employee.id,
                    )
                ],
                order="create_date desc",
            )
        )

        quotations = orders.filtered(
            lambda o: o.state
            in (
                "draft",
                "sent",
            )
        )

        rejected = orders.filtered(
            lambda o: o.nk_is_rejected
        )

        confirmed = orders.filtered(
            lambda o: o.state
            in (
                "sale",
                "done",
            )
        )

        expenses = (
            request.env[
                "nk.salesperson.expense"
            ]
            .sudo()
            .search(
                [
                    (
                        "employee_id",
                        "=",
                        employee.id,
                    )
                ],
                order="expense_date desc, id desc",
            )
        )

        values = {
            "employee": employee,

            "orders": orders,

            "quotation_count": len(
                quotations
            ),

            "confirmed_count": len(
                confirmed
            ),

            "rejected_count": len(
                rejected
            ),

            "total_amount": sum(
                orders.mapped(
                    "amount_total"
                )
            ),

            "expenses": expenses,
        }

        values.update(
            self._expense_totals(
                expenses
            )
        )

        return request.render(
            "nk_salesperson_sales_login.nk_reporting_template",
            values,
        )
