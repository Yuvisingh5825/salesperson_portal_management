# -*- coding: utf-8 -*-

from odoo import fields, models


class NkQuotationRejectWizard(models.TransientModel):
    _name = "nk.quotation.reject.wizard"
    _description = "Quotation Reject Wizard"

    order_id = fields.Many2one(
        "sale.order",
        string="Quotation",
        required=True,
        readonly=True,
    )
    reason = fields.Text(string="Reject Reason", required=True)

    def action_reject(self):
        self.ensure_one()
        self.order_id.nk_reject_quotation(self.reason)
        return {"type": "ir.actions.client", "tag": "reload"}
