# -*- coding: utf-8 -*-
"""
Field Salesperson Reporting

1. nk.salesperson.report
   One row per Sales Order.
   Used by Sales & Quotations reports.

2. nk.salesperson.invoice.report
   One row per customer invoice.
   Used by Invoice Details.

Recovery and outstanding fields are not included.
"""

from odoo import fields, models, tools


# =============================================================
# SALES ORDER REPORT
# =============================================================

class NkSalespersonReport(models.Model):
    _name = "nk.salesperson.report"
    _description = "Field Salesperson Order Report"
    _auto = False
    _rec_name = "order_name"
    _order = "order_date desc"

    order_id = fields.Many2one(
        "sale.order",
        string="Order",
        readonly=True,
    )

    order_name = fields.Char(
        string="Order Number",
        readonly=True,
    )

    nk_employee_id = fields.Many2one(
        "hr.employee",
        string="Salesperson",
        readonly=True,
    )

    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        readonly=True,
    )

    order_date = fields.Datetime(
        string="Order Date",
        readonly=True,
    )

    state = fields.Selection(
        [
            ("draft", "Quotation"),
            ("sent", "Quotation Sent"),
            ("sale", "Sales Order"),
            ("done", "Locked"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        readonly=True,
    )

    is_rejected = fields.Boolean(
        string="Rejected",
        readonly=True,
    )

    reject_reason = fields.Text(
        string="Reject Reason",
        readonly=True,
    )

    reject_date = fields.Datetime(
        string="Rejected On",
        readonly=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        readonly=True,
    )

    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        readonly=True,
    )

    amount_untaxed = fields.Monetary(
        string="Untaxed Amount",
        readonly=True,
    )

    amount_tax = fields.Monetary(
        string="Tax",
        readonly=True,
    )

    amount_total = fields.Monetary(
        string="Sales Price",
        readonly=True,
    )

    margin = fields.Monetary(
        string="Margin",
        readonly=True,
    )

    # Retained for compatibility with any existing views
    # that still reference invoice fields.
    invoice_number = fields.Char(
        string="Invoice Number",
        readonly=True,
    )

    invoice_date = fields.Date(
        string="Invoice Date",
        readonly=True,
    )

    # Survey link (quotation created from a survey)
    survey_id = fields.Many2one(
        "ionex.survey",
        string="Survey",
        readonly=True,
    )

    survey_name = fields.Char(
        string="Survey No.",
        readonly=True,
    )

    survey_type = fields.Selection(
        [
            ("ro", "R.O. Water Treatment"),
            ("cooling", "Cooling Water Treatment"),
            ("boiler", "Boiler Water Treatment"),
        ],
        string="Survey Type",
        readonly=True,
    )

    has_survey = fields.Boolean(
        string="With Survey",
        readonly=True,
    )

    invoice_status = fields.Selection(
        [
            ("not_invoiced", "Not Invoiced"),
            ("draft", "Draft"),
            ("posted", "Posted"),
        ],
        string="Invoice Status",
        readonly=True,
    )

    invoice_amount = fields.Monetary(
        string="Invoice Amount",
        readonly=True,
    )

    def action_open_order(self):
        """Open the related sales order."""
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": self.order_id.name,
            "res_model": "sale.order",
            "res_id": self.order_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def init(self):
        tools.drop_view_if_exists(
            self.env.cr,
            self._table,
        )

        self.env.cr.execute("""
            CREATE OR REPLACE VIEW nk_salesperson_report AS (

                SELECT
                    so.id AS id,
                    so.id AS order_id,
                    so.name AS order_name,
                    so.nk_employee_id AS nk_employee_id,
                    so.partner_id AS partner_id,
                    so.date_order AS order_date,
                    so.state AS state,

                    COALESCE(
                        so.nk_is_rejected,
                        FALSE
                    ) AS is_rejected,

                    so.nk_reject_reason AS reject_reason,
                    so.nk_reject_date AS reject_date,

                    so.company_id AS company_id,
                    so.currency_id AS currency_id,

                    so.amount_untaxed AS amount_untaxed,
                    so.amount_tax AS amount_tax,
                    so.amount_total AS amount_total,

                    COALESCE(
                        so.margin,
                        0
                    ) AS margin,

                    inv.invoice_number AS invoice_number,
                    inv.invoice_date AS invoice_date,

                    CASE
                        WHEN inv.origin IS NULL
                            THEN 'not_invoiced'
                        WHEN inv.has_posted
                            THEN 'posted'
                        ELSE 'draft'
                    END AS invoice_status,

                    COALESCE(
                        inv.invoice_amount,
                        0
                    ) AS invoice_amount,

                    so.ionex_survey_id AS survey_id,
                    sv.name AS survey_name,
                    sv.survey_type AS survey_type,
                    (so.ionex_survey_id IS NOT NULL) AS has_survey

                FROM sale_order so

                LEFT JOIN ionex_survey sv
                    ON sv.id = so.ionex_survey_id

                LEFT JOIN (

                    SELECT
                        am.invoice_origin AS origin,

                        STRING_AGG(
                            am.name,
                            ', '
                            ORDER BY am.id
                        ) AS invoice_number,

                        MAX(
                            am.invoice_date
                        ) AS invoice_date,

                        BOOL_OR(
                            am.state = 'posted'
                        ) AS has_posted,

                        COALESCE(
                            SUM(am.amount_total)
                            FILTER (
                                WHERE am.state = 'posted'
                            ),
                            0
                        ) AS invoice_amount

                    FROM account_move am

                    WHERE am.move_type = 'out_invoice'
                      AND am.state != 'cancel'
                      AND am.invoice_origin IS NOT NULL

                    GROUP BY am.invoice_origin

                ) inv ON inv.origin = so.name

            )
        """)


# =============================================================
# INVOICE-LEVEL REPORT
# =============================================================

class NkSalespersonInvoiceReport(models.Model):
    _name = "nk.salesperson.invoice.report"
    _description = "Field Salesperson Invoice Report"
    _auto = False
    _rec_name = "invoice_number"
    _order = "invoice_date desc, invoice_id desc"

    invoice_id = fields.Many2one(
        "account.move",
        string="Invoice",
        readonly=True,
    )

    order_id = fields.Many2one(
        "sale.order",
        string="Sales Order",
        readonly=True,
    )

    order_name = fields.Char(
        string="Order Number",
        readonly=True,
    )

    nk_employee_id = fields.Many2one(
        "hr.employee",
        string="Salesperson",
        readonly=True,
    )

    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        readonly=True,
    )

    invoice_number = fields.Char(
        string="Invoice Number",
        readonly=True,
    )

    invoice_date = fields.Date(
        string="Invoice Date",
        readonly=True,
    )

    invoice_status = fields.Selection(
        [
            ("draft", "Draft"),
            ("posted", "Posted"),
        ],
        string="Invoice Status",
        readonly=True,
    )

    invoice_amount = fields.Monetary(
        string="Invoice Amount",
        readonly=True,
        currency_field="currency_id",
    )

    amount_total = fields.Monetary(
        string="Sales Price",
        readonly=True,
        currency_field="currency_id",
    )

    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        readonly=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        readonly=True,
    )

    def action_open_invoice(self):
        """Open the actual customer invoice."""
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": self.invoice_number,
            "res_model": "account.move",
            "res_id": self.invoice_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def init(self):
        tools.drop_view_if_exists(
            self.env.cr,
            self._table,
        )

        self.env.cr.execute("""
            CREATE OR REPLACE VIEW nk_salesperson_invoice_report AS (

                SELECT
                    am.id AS id,
                    am.id AS invoice_id,

                    so.id AS order_id,
                    so.name AS order_name,
                    so.nk_employee_id AS nk_employee_id,

                    am.partner_id AS partner_id,
                    am.name AS invoice_number,
                    am.invoice_date AS invoice_date,

                    am.state AS invoice_status,

                    am.amount_total AS invoice_amount,
                    so.amount_total AS amount_total,

                    am.currency_id AS currency_id,
                    am.company_id AS company_id

                FROM account_move am

                LEFT JOIN sale_order so
                    ON so.name = am.invoice_origin

                WHERE am.move_type = 'out_invoice'
                  AND am.state IN ('draft', 'posted')

            )
        """)
