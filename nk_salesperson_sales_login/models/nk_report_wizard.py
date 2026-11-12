# -*- coding: utf-8 -*-

from datetime import datetime, time

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class NkSalespersonReportWizard(models.TransientModel):
    _name = "nk.salesperson.report.wizard"
    _description = "Field Salesperson Reporting Wizard"

    # =========================================================
    # DATE FILTER
    # =========================================================

    date_from = fields.Date(
        string="From Date",
        required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1),
    )

    date_to = fields.Date(
        string="To Date",
        required=True,
        default=fields.Date.context_today,
    )

    # =========================================================
    # REPORT SELECTION
    # =========================================================

    report_type = fields.Selection(
        [
            ("sales", "Sales & Quotations"),
            ("rejected", "Rejected Quotations"),
            ("invoice", "Invoice, Payment details"),
            ("category", "Product Category (Graph)"),
            ("profit", "Salesperson Monthly Profit"),
            ("location", "Location Tracking (Map & Route)"),
            ("expense_location", "Expense Location Wise (Graph)"),
            ("survey", "Survey Report"),
        ],
        string="Report",
        required=True,
        default="sales",
    )

    # =========================================================
    # SALESPERSON FILTER
    # =========================================================

    employee_scope = fields.Selection(
        [
            ("all", "All Salespersons"),
            ("selected", "Selected Salesperson(s)"),
        ],
        string="Salesperson",
        required=True,
        default="all",
    )

    employee_ids = fields.Many2many(
        "hr.employee",
        string="Salesperson(s)",
        domain=[("nk_employee_id", "!=", False)],
    )

    # =========================================================
    # DATE VALIDATION
    # =========================================================

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for wiz in self:
            if wiz.date_from and wiz.date_to:
                if wiz.date_from > wiz.date_to:
                    raise ValidationError(
                        "From Date cannot be after To Date."
                    )

    # =========================================================
    # SALESPERSON HELPER
    # =========================================================

    def _get_employees(self):
        self.ensure_one()

        if self.employee_scope == "selected":
            if not self.employee_ids:
                raise UserError(
                    "Please select at least one salesperson."
                )
            return self.employee_ids

        return self.env["hr.employee"].search(
            [("nk_employee_id", "!=", False)]
        )

    # =========================================================
    # DATE LABEL
    # =========================================================

    def _period_label(self):
        self.ensure_one()
        return "%s to %s" % (self.date_from, self.date_to)

    # =========================================================
    # SHOW SELECTED REPORT
    # =========================================================

    def action_show_report(self):
        self.ensure_one()

        employees = self._get_employees()

        dt_from = datetime.combine(
            self.date_from,
            time.min,
        )

        dt_to = datetime.combine(
            self.date_to,
            time.max,
        )

        # -----------------------------------------------------
        # 0. SURVEY REPORT
        # -----------------------------------------------------

        if self.report_type == "survey":

            action = self.env[
                "ir.actions.act_window"
            ]._for_xml_id(
                "nk_salesperson_sales_login."
                "action_ionex_survey"
            )

            action["domain"] = [
                ("survey_date", ">=", self.date_from),
                ("survey_date", "<=", self.date_to),
                ("employee_id", "in", employees.ids),
            ]

            action["name"] = (
                "Survey Report (%s)"
                % self._period_label()
            )

            return action

        # -----------------------------------------------------
        # 1. EXPENSE LOCATION WISE REPORT
        # -----------------------------------------------------

        if self.report_type == "expense_location":

            action = self.env[
                "ir.actions.act_window"
            ]._for_xml_id(
                "nk_salesperson_sales_login."
                "action_nk_report_expense_location"
            )

            action["domain"] = [
                ("expense_date", ">=", self.date_from),
                ("expense_date", "<=", self.date_to),
                ("employee_id", "in", employees.ids),
                ("state", "in", ("submitted", "approved")),
            ]

            action["name"] = (
                "Expense Location Wise (%s)"
                % self._period_label()
            )

            return action

        # -----------------------------------------------------
        # 2. LOCATION TRACKING
        # -----------------------------------------------------

        if self.report_type == "location":

            employee_ids = "all"

            if self.employee_scope == "selected":
                employee_ids = ",".join(
                    str(employee_id)
                    for employee_id in employees.ids
                )

            return {
                "type": "ir.actions.act_url",
                "url": (
                    "/nk_salesperson/admin/tracking/report"
                    "?employee_ids=%s&date_from=%s&date_to=%s"
                    % (
                        employee_ids,
                        self.date_from,
                        self.date_to,
                    )
                ),
                "target": "new",
            }

        # -----------------------------------------------------
        # 3. SALESPERSON MONTHLY PROFIT
        # -----------------------------------------------------

        if self.report_type == "profit":

            # One selected salesperson:
            # Open the detailed Profit Statement PDF.
            if (
                self.employee_scope == "selected"
                and len(employees) == 1
            ):
                return self.env.ref(
                    "nk_salesperson_sales_login."
                    "action_report_nk_salesperson_statement"
                ).report_action(self)

            # All or multiple salespersons:
            # Open the monthly profit report.
            lines = self.env[
                "nk.salesperson.profit.report"
            ].generate_lines(
                employees,
                self.date_from,
                self.date_to,
            )

            action = self.env[
                "ir.actions.act_window"
            ]._for_xml_id(
                "nk_salesperson_sales_login."
                "action_nk_report_profit"
            )

            action["domain"] = [
                ("id", "in", lines.ids),
            ]

            action["name"] = (
                "Salesperson Monthly Profit (%s)"
                % self._period_label()
            )

            return action

        # -----------------------------------------------------
        # 4. REPORT-WISE CONFIGURATION
        # -----------------------------------------------------

        extra_domain = []

        if self.report_type == "rejected":

            xml_id = "action_nk_report_rejected"
            date_field = "order_date"
            title = "Rejected Quotations"

            extra_domain = [
                ("is_rejected", "=", True),
            ]

        elif self.report_type == "category":

            xml_id = "action_nk_report_category"
            date_field = "order_date"
            title = "Product Category Sales"

        elif self.report_type == "invoice":

            xml_id = "action_nk_report_invoice"

            # FIX:
            # Invoice report model uses invoice_date,
            # not order_date.
            date_field = "invoice_date"

            title = "Invoice Details"

        else:

            xml_id = "action_nk_report_sales"
            date_field = "order_date"
            title = "Sales & Quotations"

            extra_domain = [
                ("is_rejected", "=", False),
            ]

        # -----------------------------------------------------
        # 5. LOAD REPORT ACTION
        # -----------------------------------------------------

        action = self.env[
            "ir.actions.act_window"
        ]._for_xml_id(
            "nk_salesperson_sales_login.%s" % xml_id
        )

        # -----------------------------------------------------
        # 6. APPLY DATE FILTER
        # -----------------------------------------------------

        if self.report_type == "invoice":

            # invoice_date is a Date field.
            date_domain = [
                (
                    "invoice_date",
                    ">=",
                    self.date_from,
                ),
                (
                    "invoice_date",
                    "<=",
                    self.date_to,
                ),
            ]

        else:

            # order_date is normally a Datetime field.
            date_domain = [
                (
                    date_field,
                    ">=",
                    dt_from,
                ),
                (
                    date_field,
                    "<=",
                    dt_to,
                ),
            ]

        # -----------------------------------------------------
        # 7. APPLY SALESPERSON AND OTHER FILTERS
        # -----------------------------------------------------

        action["domain"] = date_domain + [
            (
                "nk_employee_id",
                "in",
                employees.ids,
            ),
        ] + extra_domain

        action["name"] = "%s (%s)" % (
            title,
            self._period_label(),
        )

        return action

    # =========================================================
    # PROFIT STATEMENT DATA
    # Single salesperson
    # =========================================================

    def _get_statement_data(self):
        """
        Data for the single salesperson Profit Statement.

        Gross Revenue:
            Posted customer invoices of the salesperson's
            confirmed orders within the selected invoice-date
            period.

        Margin:
            Sale order line margin calculated for the
            invoiced quantity.

        Expenses:
            Approved food and travel expenses within the
            selected period, plus monthly mobile recharge
            and monthly salary.

        Net Profit:
            Total margin minus total expenses.
        """

        self.ensure_one()

        employee = self.employee_ids[:1]

        currency = (
            employee.nk_currency_id
            or employee.company_id.currency_id
        )

        # -----------------------------------------------------
        # GROSS REVENUE
        # -----------------------------------------------------

        orders = self.env["sale.order"].sudo().search([
            ("nk_employee_id", "=", employee.id),
            ("state", "in", ("sale", "done")),
        ])

        invoices = orders.invoice_ids.filtered(
            lambda move:
                move.move_type == "out_invoice"
                and move.state == "posted"
                and move.invoice_date
                and self.date_from
                <= move.invoice_date
                <= self.date_to
        ).sorted(
            key=lambda move: (
                move.invoice_date,
                move.id,
            )
        )

        invoice_rows = []

        for invoice in invoices:

            margin = 0.0

            product_lines = invoice.invoice_line_ids.filtered(
                lambda line: line.display_type == "product"
            )

            for line in product_lines:

                sale_lines = line.sale_line_ids.filtered(
                    lambda sale_line:
                        sale_line.order_id.nk_employee_id
                        == employee
                )

                for sale_line in sale_lines:

                    if sale_line.product_uom_qty:
                        margin += (
                            sale_line.margin
                            * line.quantity
                            / sale_line.product_uom_qty
                        )

            invoice_rows.append({
                "date": invoice.invoice_date,
                "number": invoice.name,
                "customer": invoice.partner_id.name,

                # Amount including tax:
                "amount": invoice.amount_total,

                "margin": margin,
            })

        total_invoice = sum(
            row["amount"]
            for row in invoice_rows
        )

        total_margin = sum(
            row["margin"]
            for row in invoice_rows
        )

        # -----------------------------------------------------
        # APPROVED EMPLOYEE EXPENSES
        # -----------------------------------------------------

        expenses = self.env[
            "nk.salesperson.expense"
        ].sudo().search(
            [
                ("employee_id", "=", employee.id),
                ("state", "=", "approved"),
                ("expense_date", ">=", self.date_from),
                ("expense_date", "<=", self.date_to),
            ],
            order="expense_date, id",
        )

        expense_rows = [
            {
                "date": expense.expense_date,
                "reference": expense.name,
                "food": expense.food_amount,
                "travel": expense.travel_amount,
            }
            for expense in expenses
        ]

        food_total = sum(
            row["food"]
            for row in expense_rows
        )

        travel_total = sum(
            row["travel"]
            for row in expense_rows
        )

        # -----------------------------------------------------
        # MONTHLY SALARY AND MOBILE EXPENSE
        # -----------------------------------------------------

        months = len(
            list(
                self.env[
                    "nk.salesperson.profit.report"
                ]._iter_months(
                    self.date_from,
                    self.date_to,
                )
            )
        )

        mobile_monthly = employee.nk_mobile_expense or 0.0
        salary_monthly = employee.nk_salary or 0.0

        mobile_total = mobile_monthly * months
        salary_total = salary_monthly * months

        total_expense = (
            food_total
            + travel_total
            + mobile_total
            + salary_total
        )

        # -----------------------------------------------------
        # RETURN STATEMENT DATA
        # -----------------------------------------------------

        return {
            "employee": employee,
            "currency": currency,
            "months": months,

            "invoices": invoice_rows,
            "total_invoice": total_invoice,
            "total_margin": total_margin,

            "expenses": expense_rows,
            "food_total": food_total,
            "travel_total": travel_total,

            "mobile_total": mobile_total,
            "mobile_monthly": mobile_monthly,

            "salary_total": salary_total,
            "salary_monthly": salary_monthly,

            "total_expense": total_expense,

            "net_profit": total_margin - total_expense,
        }
