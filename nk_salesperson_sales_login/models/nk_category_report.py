# -*- coding: utf-8 -*-
"""
Product category report (one row per confirmed sale order line).
Shown as GRAPH (bar / pie) - category wise sales, qty and margin.
"""

from odoo import fields, models, tools


class NkSalespersonCategoryReport(models.Model):
    _name = "nk.salesperson.category.report"
    _description = "Field Salesperson Product Category Report"
    _auto = False
    _order = "order_date desc"

    order_id = fields.Many2one("sale.order", string="Order", readonly=True)
    nk_employee_id = fields.Many2one(
        "hr.employee", string="Salesperson", readonly=True)
    order_date = fields.Datetime(string="Order Date", readonly=True)
    month = fields.Char(string="Month", readonly=True)
    categ_id = fields.Many2one(
        "product.category", string="Product Category", readonly=True)
    product_id = fields.Many2one(
        "product.product", string="Product", readonly=True)
    product_qty = fields.Float(string="Quantity", readonly=True)
    price_subtotal = fields.Monetary(string="Sales Amount", readonly=True)
    margin = fields.Monetary(string="Margin", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True)
    company_id = fields.Many2one("res.company", string="Company", readonly=True)

    def action_open_order(self):
        """Row click in the report list -> open the real sale order."""
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
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW nk_salesperson_category_report AS (
                SELECT
                    sol.id                              AS id,
                    so.id                               AS order_id,
                    so.nk_employee_id                   AS nk_employee_id,
                    so.date_order                       AS order_date,
                    TO_CHAR(so.date_order, 'YYYY-MM')   AS month,
                    pt.categ_id                         AS categ_id,
                    sol.product_id                      AS product_id,
                    sol.product_uom_qty                 AS product_qty,
                    sol.price_subtotal                  AS price_subtotal,
                    COALESCE(sol.margin, 0)             AS margin,
                    so.currency_id                      AS currency_id,
                    so.company_id                       AS company_id
                FROM sale_order_line sol
                JOIN sale_order so ON so.id = sol.order_id
                LEFT JOIN product_product pp ON pp.id = sol.product_id
                LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE sol.display_type IS NULL
                  AND so.state IN ('sale', 'done')
            )
        """)
