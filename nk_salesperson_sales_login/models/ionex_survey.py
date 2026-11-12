# -*- coding: utf-8 -*-

import re

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain

SURVEY_TYPES = [
    ("ro", "R.O. Water Treatment"),
    ("cooling", "Cooling Water Treatment"),
    ("boiler", "Boiler Water Treatment"),
]

SURVEY_STATES = [
    ("draft", "Draft"),
    ("submitted", "Submitted"),
    ("quoted", "Quoted"),
]

# Sample columns of the "Water Analysis" table (as in the paper format)
SAMPLE_COLUMNS = {
    "ro": [
        "Raw Water", "Soft/DM Water", "Feed Water",
        "Boiler Water", "Condensate",
    ],
    "boiler": [
        "Raw Water", "Soft/DM Water", "Feed Water",
        "Boiler Water", "Condensate",
    ],
    "cooling": [
        "Raw Water", "Make up Water", "Recirculation Water",
    ],
}

_COMMON_TESTS = [
    "pH",
    "Total Hardness",
    "P-Alkalinity",
    "M-Alkalinity",
    "Chloride",
    "Residual Phosphate",
]
_BOILER_TESTS = ["Residual Sulphite/N2H4", "Residual Amine"]
_END_TESTS = ["Total Dissolved Solids", "Total Suspended Solids"]

ANALYSIS_TESTS = {
    "ro": _COMMON_TESTS + _BOILER_TESTS + _END_TESTS,
    "boiler": _COMMON_TESTS + _BOILER_TESTS + _END_TESTS,
    "cooling": _COMMON_TESTS + _END_TESTS,
}


def _digits(value):
    """Phone number -> only digits (last 10), for duplicate check."""
    return re.sub(r"\D", "", value or "")[-10:]


class IonexSurvey(models.Model):
    _name = "ionex.survey"
    _description = "Water Treatment Survey"
    _order = "survey_date desc, id desc"
    _inherit = ["mail.thread"]

    name = fields.Char(
        string="Survey No.",
        required=True,
        copy=False,
        readonly=True,
        default="New",
        index=True,
    )
    survey_type = fields.Selection(
        SURVEY_TYPES,
        string="Survey Type",
        required=True,
        default="ro",
        tracking=True,
    )
    state = fields.Selection(
        SURVEY_STATES,
        string="Status",
        default="draft",
        required=True,
        copy=False,
        index=True,
        tracking=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Salesperson",
        required=True,
        index=True,
        ondelete="restrict",
        default=lambda self: self.env["sale.order"]._get_current_nk_employee(),
    )
    survey_date = fields.Date(
        string="Date of Survey",
        required=True,
        default=fields.Date.context_today,
    )

    # ---- Customer ----
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        index=True,
        ondelete="restrict",
    )
    is_new_customer = fields.Boolean(string="New Customer")
    new_company = fields.Char(string="New Customer - Company (M/s)")
    new_address = fields.Text(string="New Customer - Address")
    new_phone = fields.Char(string="New Customer - Tel. / Fax")

    customer_name = fields.Char(
        string="Company",
        compute="_compute_customer_name",
        store=True,
    )

    # ---- Person visited ----
    visited_person = fields.Char(string="Person Visited")
    visited_designation = fields.Char(string="Designation")
    proposal_person = fields.Char(string="Proposal in the Name of")
    proposal_designation = fields.Char(string="Designation (Proposal)")

    contact_ids = fields.One2many(
        "ionex.survey.contact", "survey_id", string="Contact Persons")

    # ---- R.O. system details ----
    ro_capacity = fields.Char(string="Capacity of R.O.")
    ro_pressure = fields.Char(string="Working Pressure")
    ro_flow = fields.Char(string="Flow of R.O.")

    # ---- Cooling system details ----
    cool_towers = fields.Char(string="No. of Cooling Towers")
    cool_tower_type = fields.Selection(
        [
            ("induced", "Induced Draft"),
            ("forced", "Forced Draft"),
            ("natural", "Natural"),
            ("spray", "Spray Pond"),
        ],
        string="Type of Cooling Towers",
    )
    cool_recirculation = fields.Char(
        string="Recirculation (LPS/LPM/LPH/M3/Hr)")
    cool_temp_diff = fields.Char(
        string="Temperature Difference (Inlet & Outlet, C/F)")
    cool_makeup_quality = fields.Char(string="Quality of Makeup Water")
    cool_sump_volume = fields.Char(string="Hold up Volume of Sump (M3)")

    # ---- Boiler system details ----
    boiler_no = fields.Char(string="No. of Boilers")
    boiler_make = fields.Char(string="Make of Boilers")
    boiler_capacity = fields.Char(string="Capacity of Boilers")
    boiler_type = fields.Selection(
        [
            ("water", "Water Tube"),
            ("fire", "Fire Tube"),
            ("both", "Water & Fire Tube"),
        ],
        string="Type of Boiler",
    )
    boiler_pressure = fields.Char(string="Working Pressure")
    boiler_steam = fields.Char(string="Average Steam Production")
    boiler_condensate_pct = fields.Char(string="% of Return Condensate")
    boiler_feed_temp = fields.Char(string="Feed Water Temperature")
    boiler_blowdown_pct = fields.Char(string="Blow down %")
    boiler_feed_quality = fields.Char(string="Quality of Feed Water")
    boiler_makeup_quality = fields.Char(string="Quality of Makeup Water")

    # ---- Tables ----
    analysis_ids = fields.One2many(
        "ionex.survey.analysis", "survey_id", string="Water Analysis")
    treatment_ids = fields.One2many(
        "ionex.survey.treatment", "survey_id",
        string="Details of Present Treatment")

    # ---- Problems faced ----
    prob_scaling = fields.Boolean(string="Scaling")
    prob_corrosion = fields.Boolean(string="Corrosion")
    prob_carry_over = fields.Boolean(string="Carry Over")
    prob_fouling = fields.Boolean(string="Fouling")
    prob_expensive = fields.Boolean(string="More Expensive")
    sample_legend = fields.Char(
        string="Analysis Columns", compute="_compute_labels")
    type_label = fields.Char(
        string="Type Label", compute="_compute_labels")
    state_label = fields.Char(
        string="Status Label", compute="_compute_labels")
    problems_text = fields.Char(
        string="Problems Faced",
        compute="_compute_problems_text",
    )
    remarks = fields.Text(string="Remarks")

    # ---- Proposal ----
    product_ids = fields.One2many(
        "ionex.survey.product", "survey_id", string="Proposal Products")
    amount_total = fields.Float(
        string="Proposal Amount",
        compute="_compute_amount_total",
        store=True,
    )
    customer_signature = fields.Binary(
        string="Customer Signature", attachment=True)

    # ---- Quotation ----
    order_id = fields.Many2one(
        "sale.order",
        string="Quotation",
        copy=False,
        readonly=True,
        index=True,
        ondelete="set null",
    )
    order_state = fields.Selection(
        related="order_id.state", string="Quotation Status")
    quotation_amount = fields.Monetary(
        related="order_id.amount_total",
        string="Quotation Amount",
        currency_field="order_currency_id",
    )
    order_currency_id = fields.Many2one(
        related="order_id.currency_id", string="Quotation Currency")
    is_locked = fields.Boolean(
        string="Locked",
        compute="_compute_is_locked",
    )

    # =========================================================
    # COMPUTE
    # =========================================================

    @api.depends(
        "partner_id.name", "is_new_customer", "new_company")
    def _compute_customer_name(self):
        for survey in self:
            survey.customer_name = (
                survey.partner_id.name
                or survey.new_company
                or ""
            )

    @api.depends("survey_type", "state")
    def _compute_labels(self):
        types = dict(SURVEY_TYPES)
        states = dict(SURVEY_STATES)
        for survey in self:
            survey.type_label = types.get(survey.survey_type, "")
            survey.state_label = states.get(survey.state, "")
            survey.sample_legend = " | ".join(
                "Sample %d = %s" % (i + 1, name)
                for i, name in enumerate(
                    SAMPLE_COLUMNS.get(survey.survey_type, []))
            )

    @api.depends(
        "prob_scaling", "prob_corrosion", "prob_carry_over",
        "prob_fouling", "prob_expensive")
    def _compute_problems_text(self):
        labels = [
            ("prob_scaling", "Scaling"),
            ("prob_corrosion", "Corrosion"),
            ("prob_carry_over", "Carry Over"),
            ("prob_fouling", "Fouling"),
            ("prob_expensive", "More Expensive"),
        ]
        for survey in self:
            survey.problems_text = ", ".join(
                label for field, label in labels if survey[field])

    @api.depends("product_ids.subtotal")
    def _compute_amount_total(self):
        for survey in self:
            survey.amount_total = sum(survey.product_ids.mapped("subtotal"))

    @api.depends("order_id.state")
    def _compute_is_locked(self):
        for survey in self:
            survey.is_locked = survey.order_id.state in ("sale", "done")

    # =========================================================
    # CREATE / WRITE / SEARCH
    # =========================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].sudo().next_by_code("ionex.survey")
                    or "New"
                )
        return super().create(vals_list)

    def write(self, vals):
        # Survey is locked once its quotation is confirmed.
        if not self.env.context.get("ionex_survey_force"):
            locked = self.filtered("is_locked")
            allowed = {"message_follower_ids", "message_ids"}
            if locked and set(vals) - allowed:
                raise UserError(
                    "Survey %s is locked because its quotation is "
                    "confirmed." % ", ".join(locked.mapped("name"))
                )
        return super().write(vals)

    def unlink(self):
        for survey in self:
            if survey.state != "draft":
                raise UserError(
                    "Only a Draft survey can be deleted (%s)." % survey.name)
        return super().unlink()

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        """salesperson (backend user) -> only own surveys."""
        if self.env.su:
            return super()._search(
                domain, offset=offset, limit=limit, order=order, **kwargs)

        user = self.env.user
        is_manager = (
            user.has_group("base.group_system")
            or user.has_group("sales_team.group_sale_manager")
            or user.has_group(
                "nk_salesperson_sales_login.group_nk_salesperson_manager")
        )
        if not is_manager and user.has_group(
                "nk_salesperson_sales_login.group_nk_salesperson"):
            employee_id = self.env["sale.order"]._get_current_nk_employee()
            extra = (
                [("employee_id", "=", employee_id)]
                if employee_id else [("id", "=", False)]
            )
            domain = Domain(domain) & Domain(extra)

        return super()._search(
            domain, offset=offset, limit=limit, order=order, **kwargs)

    # =========================================================
    # HELPERS
    # =========================================================

    @api.model
    def default_analysis_rows(self, survey_type):
        """[(test name, [''] * columns)] for the water analysis table."""
        cols = len(SAMPLE_COLUMNS.get(survey_type, []))
        return [
            (test, [""] * cols)
            for test in ANALYSIS_TESTS.get(survey_type, [])
        ]

    @api.model
    def _find_duplicate_partner(self, name, phone):
        """Existing customer with the same name or phone, else empty."""
        Partner = self.env["res.partner"].sudo().with_context(
            active_test=False)

        name = (name or "").strip()
        if name:
            found = Partner.search(
                [("name", "=ilike", name), ("parent_id", "=", False)],
                limit=1,
            )
            if found:
                return found

        digits = _digits(phone)
        if len(digits) >= 7:
            fields_list = ["phone"]
            if "mobile" in Partner._fields:
                fields_list.append("mobile")
            domain = [(f, "!=", False) for f in fields_list]
            if len(domain) > 1:
                domain = ["|"] + domain
            for partner in Partner.search(domain, limit=5000):
                for f in fields_list:
                    if _digits(partner[f]) == digits:
                        return partner
        return Partner.browse()

    def _ensure_partner(self):
        """Create the new customer (and its contacts) if needed."""
        self.ensure_one()
        survey = self.sudo()
        if survey.partner_id:
            return survey.partner_id

        company = (survey.new_company or "").strip()
        if not company:
            raise UserError("Please select a customer or add a new customer.")

        duplicate = self._find_duplicate_partner(company, survey.new_phone)
        if duplicate:
            raise UserError(
                "Customer already exists: %s. Please select it from the "
                "customer list instead of adding a new one." % duplicate.name
            )

        Partner = self.env["res.partner"].sudo()
        vals = {
            "name": company,
            "company_type": "company",
            "street": survey.new_address or False,
            "phone": survey.new_phone or False,
        }
        if "customer_rank" in Partner._fields:
            vals["customer_rank"] = 1
        partner = Partner.create(vals)

        for contact in survey.contact_ids:
            if (contact.name or "").strip():
                Partner.create({
                    "name": contact.name.strip(),
                    "function": contact.designation or False,
                    "parent_id": partner.id,
                    "type": "contact",
                })

        survey.write({"partner_id": partner.id})
        return partner

    # =========================================================
    # ACTIONS
    # =========================================================

    def action_submit(self):
        for survey in self:
            if survey.state != "draft":
                continue
            survey._ensure_partner()
            survey.write({"state": "submitted"})
        return True

    def action_set_draft(self):
        for survey in self:
            if survey.order_id and survey.order_id.state != "cancel":
                raise UserError(
                    "Survey %s already has quotation %s."
                    % (survey.name, survey.order_id.name)
                )
            survey.write({"state": "draft", "order_id": False})
        return True

    def action_create_quotation(self):
        """Create the quotation from Proposal Products."""
        self.ensure_one()
        survey = self.sudo()

        if survey.order_id and survey.order_state != "cancel":
            return survey.order_id
        lines = survey.product_ids.filtered("product_id")
        if not lines:
            raise UserError(
                "Add at least one Proposal Product to create a quotation.")

        partner = survey._ensure_partner()

        order = self.env["sale.order"].sudo().create({
            "partner_id": partner.id,
            "nk_employee_id": survey.employee_id.id,
            "ionex_survey_id": survey.id,
            "order_line": [
                (0, 0, {
                    "product_id": line.product_id.id,
                    "product_uom_qty": line.qty,
                    "price_unit": line.price_unit,
                })
                for line in lines
            ],
        })
        survey.write({"order_id": order.id, "state": "quoted"})
        order.message_post(
            body="Created from survey %s." % survey.name)
        return order

    def action_open_quotation(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "res_id": self.order_id.id,
            "view_mode": "form",
        }


class IonexSurveyContact(models.Model):
    _name = "ionex.survey.contact"
    _description = "Survey Contact Person"
    _order = "sequence, id"

    survey_id = fields.Many2one(
        "ionex.survey", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Name")
    designation = fields.Char(string="Designation")


class IonexSurveyAnalysis(models.Model):
    _name = "ionex.survey.analysis"
    _description = "Survey Water Analysis"
    _order = "sequence, id"

    survey_id = fields.Many2one(
        "ionex.survey", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    test = fields.Char(string="Test")
    col1 = fields.Char(string="Sample 1")
    col2 = fields.Char(string="Sample 2")
    col3 = fields.Char(string="Sample 3")
    col4 = fields.Char(string="Sample 4")
    col5 = fields.Char(string="Sample 5")


class IonexSurveyTreatment(models.Model):
    _name = "ionex.survey.treatment"
    _description = "Survey Present Treatment"
    _order = "sequence, id"

    survey_id = fields.Many2one(
        "ionex.survey", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    make = fields.Char(string="Make of Product")
    supplier = fields.Char(string="Supplied by M/s")
    chemical_form = fields.Selection(
        [("liquid", "Liquid"), ("solid", "Solid")],
        string="Form of Chemicals",
    )
    dosage = fields.Char(string="Dosage of Chemicals")
    price = fields.Char(string="Price of Chemicals (Rs.)")


class IonexSurveyProduct(models.Model):
    _name = "ionex.survey.product"
    _description = "Survey Proposal Product"
    _order = "sequence, id"

    survey_id = fields.Many2one(
        "ionex.survey", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        domain=[("sale_ok", "=", True)],
    )
    qty = fields.Float(string="Qty", default=1.0)
    price_unit = fields.Float(string="Unit Price")
    subtotal = fields.Float(
        string="Subtotal",
        compute="_compute_subtotal",
        store=True,
    )

    @api.depends("qty", "price_unit")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.qty * line.price_unit

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id and not self.price_unit:
            self.price_unit = self.product_id.list_price
