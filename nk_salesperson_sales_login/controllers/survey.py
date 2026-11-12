# -*- coding: utf-8 -*-

from datetime import date
from urllib.parse import quote

from odoo import fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from werkzeug.exceptions import NotFound

from ..models.ionex_survey import (
    ANALYSIS_TESTS,
    SAMPLE_COLUMNS,
    SURVEY_STATES,
    SURVEY_TYPES,
)

TYPE_LABELS = dict(SURVEY_TYPES)
STATE_LABELS = dict(SURVEY_STATES)

PROBLEMS = {
    "ro": [
        ("prob_scaling", "Scaling"),
        ("prob_corrosion", "Corrosion"),
        ("prob_carry_over", "Carry Over"),
        ("prob_expensive", "More Expensive"),
    ],
    "boiler": [
        ("prob_scaling", "Scaling"),
        ("prob_corrosion", "Corrosion"),
        ("prob_carry_over", "Carry Over"),
        ("prob_expensive", "More Expensive"),
    ],
    "cooling": [
        ("prob_scaling", "Scaling"),
        ("prob_corrosion", "Corrosion"),
        ("prob_fouling", "Fouling"),
    ],
}

# System detail fields of every survey type (plain text fields)
SYSTEM_FIELDS = {
    "ro": ["ro_capacity", "ro_pressure", "ro_flow"],
    "cooling": [
        "cool_towers", "cool_recirculation", "cool_temp_diff",
        "cool_makeup_quality", "cool_sump_volume",
    ],
    "boiler": [
        "boiler_no", "boiler_make", "boiler_capacity", "boiler_pressure",
        "boiler_steam", "boiler_condensate_pct", "boiler_feed_temp",
        "boiler_blowdown_pct", "boiler_feed_quality",
        "boiler_makeup_quality",
    ],
}
SELECTION_FIELDS = {
    "cooling": {
        "cool_tower_type": ["induced", "forced", "natural", "spray"],
    },
    "boiler": {
        "boiler_type": ["water", "fire", "both"],
    },
}

CONTACT_SLOTS = 3
TREATMENT_SLOTS = 4
MIN_PRODUCT_ROWS = 5


def _to_float(value, default=0.0):
    try:
        return float((value or "").strip() or default)
    except (TypeError, ValueError):
        return None


class IonexSurveyController(http.Controller):

    # =========================================================
    # HELPERS
    # =========================================================

    def _get_employee(self):
        Employee = request.env["hr.employee"]
        employee_id = request.session.get("nk_salesperson_employee_id")
        if not employee_id:
            return Employee
        return Employee.sudo().browse(employee_id).exists()

    def _go(self, path, message=None, kind="success"):
        if message:
            path = "%s%s%s=%s" % (
                path, "&" if "?" in path else "?", kind, quote(message))
        return request.redirect(path)

    def _get_own_survey(self, employee, survey_id):
        survey = request.env["ionex.survey"].sudo().browse(survey_id).exists()
        if not survey or survey.employee_id != employee:
            raise NotFound()
        return survey

    def _partner_options(self, employee, survey=None):
        Partner = request.env["res.partner"].sudo()
        own_ids = (
            request.env["sale.order"].sudo()
            .search([("nk_employee_id", "=", employee.id)])
            .mapped("partner_id").ids
        )
        domain = [("active", "=", True), ("parent_id", "=", False)]
        if "customer_rank" in Partner._fields:
            domain += ["|", ("customer_rank", ">", 0), ("id", "in", own_ids)]
        else:
            domain += [("id", "in", own_ids)]
        partners = Partner.search(domain, order="name", limit=500)
        if survey and survey.partner_id:
            partners |= survey.partner_id
        return partners.sorted("name")

    def _product_options(self, survey=None):
        Product = request.env["product.product"].sudo()
        products = Product.search(
            [("sale_ok", "=", True)], order="name", limit=500)
        if survey:
            products |= survey.product_ids.mapped("product_id")
        return products.sorted("display_name")

    def _form_values(self, employee, survey, stype, success=None, error=None):
        Survey = request.env["ionex.survey"].sudo()
        cols = SAMPLE_COLUMNS[stype]

        # Water analysis rows
        saved = {a.test: a for a in survey.analysis_ids} if survey else {}
        analysis = []
        for index, (test, _blank) in enumerate(
                Survey.default_analysis_rows(stype)):
            rec = saved.get(test)
            analysis.append({
                "index": index,
                "test": test,
                "vals": [
                    (rec["col%d" % (i + 1)] if rec else "") or ""
                    for i in range(len(cols))
                ],
            })

        # Contact persons
        contacts = [
            {"name": c.name or "", "designation": c.designation or ""}
            for c in (survey.contact_ids if survey else [])
        ][:CONTACT_SLOTS]
        while len(contacts) < CONTACT_SLOTS:
            contacts.append({"name": "", "designation": ""})

        # Present treatment (4 products)
        treatments = [
            {
                "make": t.make or "",
                "supplier": t.supplier or "",
                "form": t.chemical_form or "",
                "dosage": t.dosage or "",
                "price": t.price or "",
            }
            for t in (survey.treatment_ids if survey else [])
        ]
        while len(treatments) < TREATMENT_SLOTS:
            treatments.append(
                {"make": "", "supplier": "", "form": "",
                 "dosage": "", "price": ""})

        # Proposal products
        products = [
            {"product_id": p.product_id.id, "qty": p.qty,
             "price": p.price_unit}
            for p in (survey.product_ids if survey else [])
        ]
        while len(products) < MIN_PRODUCT_ROWS:
            products.append({"product_id": False, "qty": 1.0, "price": 0.0})

        readonly = bool(survey and (survey.state == "quoted"))

        signature_src = False
        if survey and survey.customer_signature:
            raw = survey.customer_signature
            if isinstance(raw, bytes):
                raw = raw.decode("ascii")
            signature_src = "data:image/png;base64," + raw

        return {
            "employee": employee,
            "survey": survey,
            "stype": stype,
            "type_label": TYPE_LABELS[stype],
            "cols": cols,
            "analysis": analysis,
            "contacts": contacts,
            "treatments": treatments,
            "products": products,
            "problems": PROBLEMS[stype],
            "partners": self._partner_options(employee, survey),
            "product_options": self._product_options(survey),
            "readonly": readonly,
            "signature_src": signature_src,
            "today": fields.Date.context_today(request.env.user),
            "success": success,
            "error": error,
        }

    # =========================================================
    # NEW QUOTATION -> choose Normal / With Survey
    # (the choice page itself is /nk_salesperson/quotation/new)
    # =========================================================

    @http.route(
        "/nk_salesperson/quotation/new/normal",
        type="http", auth="public", website=True, methods=["GET"],
    )
    def new_quotation_normal(self, **kw):
        if not self._get_employee():
            return request.redirect("/nk_salesperson/login")
        return request.redirect("/web#model=sale.order&view_type=form")

    # =========================================================
    # SURVEY LIST (My Surveys)
    # =========================================================

    @http.route(
        "/nk_salesperson/surveys",
        type="http", auth="public", website=True, methods=["GET"],
    )
    def survey_list(
            self, stype=None, state=None, date_from=None, date_to=None,
            success=None, error=None, **kw):

        employee = self._get_employee()
        if not employee:
            return request.redirect("/nk_salesperson/login")

        domain = [("employee_id", "=", employee.id)]
        if stype in TYPE_LABELS:
            domain.append(("survey_type", "=", stype))
        if state in STATE_LABELS:
            domain.append(("state", "=", state))
        for key, op, value in (
                ("survey_date", ">=", date_from),
                ("survey_date", "<=", date_to)):
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    continue
                domain.append((key, op, value))

        surveys = request.env["ionex.survey"].sudo().search(
            domain, order="survey_date desc, id desc", limit=500)

        return request.render(
            "nk_salesperson_sales_login.ionex_survey_list_template",
            {
                "employee": employee,
                "surveys": surveys,
                "type_labels": TYPE_LABELS,
                "state_labels": STATE_LABELS,
                "f_stype": stype or "",
                "f_state": state or "",
                "f_date_from": date_from or "",
                "f_date_to": date_to or "",
                "success": success,
                "error": error,
            },
        )

    # =========================================================
    # SURVEY FORM
    # =========================================================

    @http.route(
        "/nk_salesperson/survey/new/<string:stype>",
        type="http", auth="public", website=True, methods=["GET"],
    )
    def survey_new(self, stype, success=None, error=None, **kw):
        employee = self._get_employee()
        if not employee:
            return request.redirect("/nk_salesperson/login")
        if stype not in TYPE_LABELS:
            raise NotFound()

        survey = request.env["ionex.survey"].sudo().browse()
        return request.render(
            "nk_salesperson_sales_login.ionex_survey_form_template",
            self._form_values(employee, survey, stype, success, error),
        )

    @http.route(
        "/nk_salesperson/survey/<int:survey_id>",
        type="http", auth="public", website=True, methods=["GET"],
    )
    def survey_open(self, survey_id, success=None, error=None, **kw):
        employee = self._get_employee()
        if not employee:
            return request.redirect("/nk_salesperson/login")

        survey = self._get_own_survey(employee, survey_id)
        return request.render(
            "nk_salesperson_sales_login.ionex_survey_form_template",
            self._form_values(
                employee, survey, survey.survey_type, success, error),
        )

    # =========================================================
    # SAVE
    # =========================================================

    def _parse_form(self, form, stype):
        g = lambda key: (form.get(key) or "").strip()  # noqa: E731
        Partner = request.env["res.partner"].sudo()

        vals = {
            "survey_type": stype,
            "visited_person": g("visited_person"),
            "visited_designation": g("visited_designation"),
            "proposal_person": g("proposal_person"),
            "proposal_designation": g("proposal_designation"),
            "remarks": g("remarks"),
        }

        survey_date = g("survey_date")
        try:
            date.fromisoformat(survey_date)
            vals["survey_date"] = survey_date
        except ValueError:
            vals["survey_date"] = fields.Date.context_today(request.env.user)

        # ---- Customer ----
        if g("customer_mode") == "new":
            vals.update({
                "is_new_customer": True,
                "partner_id": False,
                "new_company": g("new_company"),
                "new_address": g("new_address"),
                "new_phone": g("new_phone"),
            })
        else:
            partner = Partner.browse()
            if g("partner_id").isdigit():
                partner = Partner.browse(int(g("partner_id"))).exists()
            vals.update({
                "is_new_customer": False,
                "partner_id": partner.id or False,
                "new_company": False,
                "new_address": False,
                "new_phone": False,
            })

        # ---- System details ----
        for field_name in SYSTEM_FIELDS[stype]:
            vals[field_name] = g(field_name)
        for field_name, allowed in SELECTION_FIELDS.get(stype, {}).items():
            value = g(field_name)
            vals[field_name] = value if value in allowed else False

        # ---- Problems ----
        for field_name in (
                "prob_scaling", "prob_corrosion", "prob_carry_over",
                "prob_fouling", "prob_expensive"):
            vals[field_name] = False
        for field_name, _label in PROBLEMS[stype]:
            vals[field_name] = bool(form.get(field_name))

        # ---- Contact persons ----
        contact_cmds = [(5, 0, 0)]
        for i in range(1, CONTACT_SLOTS + 1):
            name = g("contact_name_%d" % i)
            desig = g("contact_desig_%d" % i)
            if name or desig:
                contact_cmds.append((0, 0, {
                    "sequence": i, "name": name, "designation": desig}))
        vals["contact_ids"] = contact_cmds

        # ---- Water analysis ----
        analysis_cmds = [(5, 0, 0)]
        ncols = len(SAMPLE_COLUMNS[stype])
        for index, test in enumerate(ANALYSIS_TESTS[stype]):
            row = {"sequence": index + 1, "test": test}
            for c in range(ncols):
                row["col%d" % (c + 1)] = g("a_%d_%d" % (index, c))
            analysis_cmds.append((0, 0, row))
        vals["analysis_ids"] = analysis_cmds

        # ---- Present treatment ----
        treatment_cmds = [(5, 0, 0)]
        makes = form.getlist("t_make")
        suppliers = form.getlist("t_supplier")
        forms_ = form.getlist("t_form")
        dosages = form.getlist("t_dosage")
        prices_ = form.getlist("t_price")

        def _at(values, index):
            return (values[index] if index < len(values) else "").strip()

        for i in range(len(makes)):
            row = {
                "make": _at(makes, i),
                "supplier": _at(suppliers, i),
                "dosage": _at(dosages, i),
                "price": _at(prices_, i),
            }
            chem_form = _at(forms_, i)
            row["chemical_form"] = (
                chem_form if chem_form in ("liquid", "solid") else False)
            if any(row.values()):
                row["sequence"] = i + 1
                treatment_cmds.append((0, 0, row))
        vals["treatment_ids"] = treatment_cmds

        # ---- Proposal products ----
        product_cmds = [(5, 0, 0)]
        product_ids = form.getlist("product_id")
        qtys = form.getlist("qty")
        prices = form.getlist("price")
        Product = request.env["product.product"].sudo()
        for i, product_id in enumerate(product_ids):
            if not (product_id or "").isdigit():
                continue
            product = Product.browse(int(product_id)).exists()
            if not product:
                continue
            qty = _to_float(qtys[i] if i < len(qtys) else "", 1.0)
            price = _to_float(prices[i] if i < len(prices) else "", 0.0)
            if qty is None or price is None or qty <= 0 or price < 0:
                raise ValidationError(
                    "Invalid quantity or price for %s." % product.display_name)
            product_cmds.append((0, 0, {
                "sequence": i + 1,
                "product_id": product.id,
                "qty": qty,
                "price_unit": price,
            }))
        vals["product_ids"] = product_cmds

        # ---- Customer signature (drawn on the screen) ----
        signature = g("signature")
        prefix = "data:image/png;base64,"
        if signature.startswith(prefix) and len(signature) > len(prefix):
            vals["customer_signature"] = signature[len(prefix):]

        return vals

    @http.route(
        "/nk_salesperson/survey/save",
        type="http", auth="public", website=True, methods=["POST"],
    )
    def survey_save(self, **kw):
        employee = self._get_employee()
        if not employee:
            return request.redirect("/nk_salesperson/login")

        form = request.httprequest.form
        action = form.get("action") or "draft"
        Survey = request.env["ionex.survey"].sudo()

        survey_id = form.get("survey_id") or ""
        if survey_id.isdigit() and int(survey_id):
            survey = self._get_own_survey(employee, int(survey_id))
            stype = survey.survey_type
            if survey.state == "quoted":
                return self._go(
                    "/nk_salesperson/survey/%d" % survey.id,
                    "This survey already has a quotation and cannot "
                    "be changed.", "error")
        else:
            survey = Survey.browse()
            stype = form.get("survey_type")
            if stype not in TYPE_LABELS:
                raise NotFound()

        # 1) Save the data first (so nothing is lost on a later error)
        try:
            with request.env.cr.savepoint():
                vals = self._parse_form(form, stype)
                if survey:
                    survey.write(vals)
                else:
                    vals["employee_id"] = employee.id
                    survey = Survey.create(vals)
        except (UserError, ValidationError) as exc:
            back = (
                "/nk_salesperson/survey/%d" % survey.id
                if survey else "/nk_salesperson/survey/new/%s" % stype
            )
            return self._go(back, str(exc), "error")

        path = "/nk_salesperson/survey/%d" % survey.id

        # 2) Draft / plain save
        if action in ("draft", "save"):
            return self._go(
                path,
                "Draft saved." if survey.state == "draft"
                else "Survey saved.")

        # 3) Submit (and create quotation)
        has_products = bool(survey.product_ids.filtered("product_id"))
        order = request.env["sale.order"].sudo().browse()
        try:
            with request.env.cr.savepoint():
                survey.action_submit()
                if has_products:
                    order = survey.action_create_quotation()
        except (UserError, ValidationError) as exc:
            return self._go(path, str(exc), "error")

        if not order:
            return self._go(
                path,
                "Survey submitted. Add Proposal Products to create "
                "the quotation.")

        return self._go(
            "/nk_salesperson/quotation/%d" % order.id,
            "Quotation created from survey %s." % survey.name)

    # =========================================================
    # CREATE QUOTATION FROM A SUBMITTED SURVEY
    # =========================================================

    @http.route(
        "/nk_salesperson/survey/<int:survey_id>/create_quotation",
        type="http", auth="public", website=True, methods=["POST"],
    )
    def survey_create_quotation(self, survey_id, **kw):
        employee = self._get_employee()
        if not employee:
            return request.redirect("/nk_salesperson/login")

        survey = self._get_own_survey(employee, survey_id)
        path = "/nk_salesperson/survey/%d" % survey.id
        try:
            with request.env.cr.savepoint():
                if survey.state == "draft":
                    survey.action_submit()
                order = survey.action_create_quotation()
        except (UserError, ValidationError) as exc:
            return self._go(path, str(exc), "error")

        return self._go(
            "/nk_salesperson/quotation/%d" % order.id,
            "Quotation created from survey %s." % survey.name)
