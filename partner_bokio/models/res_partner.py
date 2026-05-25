import os
import sys
from pathlib import Path

from odoo import fields, models
from odoo.exceptions import UserError

# Make bokio_api importable when running inside the Odoo container.
# The addon is mounted at /mnt/addons/odoo_bokio_api/partner_bokio/models/
# so two levels up is the repo root which contains the bokio_api package.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


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

    def action_sync_to_bokio(self):
        """Sync selected partners to Bokio. Bound to the list view Actions menu."""
        try:
            from bokio_api import BokioClient, BokioAPIError
        except ImportError as exc:
            raise UserError(
                f"bokio_api package not found. Make sure the repo is mounted correctly.\n{exc}"
            ) from exc

        token = os.environ.get("BOKIO_TOKEN")
        company_id = os.environ.get("BOKIO_COMPANY_ID")
        if not token or not company_id:
            raise UserError(
                "BOKIO_TOKEN and BOKIO_COMPANY_ID must be set in the server environment."
            )

        client = BokioClient(token=token, company_id=company_id)
        created = updated = skipped = errors = 0
        error_lines: list[str] = []

        for partner in self:
            name = (partner.name or "").strip()
            if not name:
                skipped += 1
                continue

            country = partner.country_id.name if partner.country_id else "SE"
            org_number = None
            if partner.is_company:
                org_number = partner.vat or None
            else:
                org_number = getattr(partner, "personnummer", None) or None

            payload = BokioClient.build_payload(
                name=name,
                is_company=bool(partner.is_company),
                org_number=org_number,
                vat=partner.vat if partner.is_company else None,
                street=partner.street,
                street2=partner.street2,
                zip_code=partner.zip,
                city=partner.city,
                country=country,
                email=partner.email,
                phone=partner.phone,
            )

            try:
                if partner.bokio_id:
                    try:
                        client.update_customer(partner.bokio_id, payload)
                        partner.write({"bokio_synced_at": fields.Datetime.now()})
                        updated += 1
                    except BokioAPIError as exc:
                        if exc.status_code in (404, 405):
                            skipped += 1
                        else:
                            raise
                else:
                    result = client.create_customer(payload)
                    bokio_id = result.get("id") or result.get("customerId") or ""
                    partner.write({
                        "bokio_id": bokio_id,
                        "bokio_synced_at": fields.Datetime.now(),
                    })
                    created += 1
            except BokioAPIError as exc:
                error_lines.append(f"{name}: {exc}")
                errors += 1

        # Build result notification
        summary = f"Created: {created}  Updated: {updated}  Skipped: {skipped}"
        if errors:
            summary += f"  Errors: {errors}"
        if error_lines:
            summary += "\n" + "\n".join(error_lines)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Bokio Sync",
                "message": summary,
                "type": "success" if not errors else "warning",
                "sticky": bool(errors),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
