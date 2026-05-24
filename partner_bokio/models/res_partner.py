from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    bokio_id = fields.Char(
        string="Bokio UUID",
        copy=False,
        index=True,
        help="UUID assigned by Bokio for this customer.",
    )
    bokio_customer_number = fields.Char(
        string="Bokio Customer No.",
        copy=False,
        help="Visible customer number in Bokio UI (reserved — not always exposed via API).",
    )
    bokio_synced_at = fields.Datetime(
        string="Last Synced (Bokio)",
        readonly=True,
        copy=False,
        help="Timestamp of the last successful sync with Bokio.",
    )
    bokio_master = fields.Selection(
        selection=[("odoo", "Odoo"), ("bokio", "Bokio")],
        string="Master System",
        default="bokio",
        required=True,
        help="Authoritative data source for this contact. "
             "Bokio → Odoo receives on sync. Odoo → Odoo pushes to Bokio.",
    )
