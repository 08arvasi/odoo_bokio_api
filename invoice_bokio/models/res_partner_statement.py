from odoo import models


class ResPartnerStatement(models.Model):
    _inherit = "res.partner"

    def action_send_statement(self):
        self.ensure_one()
        template = self.env.ref(
            "invoice_bokio.mail_template_partner_statement",
            raise_if_not_found=False,
        )
        return {
            "type": "ir.actions.act_window",
            "name": "Skicka fakturautdrag",
            "res_model": "mail.compose.message",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_model": "res.partner",
                "default_res_ids": self.ids,
                "default_template_id": template.id if template else False,
                "default_composition_mode": "comment",
                "force_email": True,
            },
        }
