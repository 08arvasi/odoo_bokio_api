import os
import sys
from pathlib import Path

from odoo import Command, api, fields, models
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
        selection=[
            ("bokio", "Bokio"),
            ("odoo", "Odoo"),
            ("none", "Odoo only"),
        ],
        string="Master System",
        default="bokio",
        required=True,
        help="Authoritative data source for this contact.\n"
             "Bokio → Odoo reads from Bokio; never overwritten by Odoo.\n"
             "Odoo → Odoo pushes to Bokio (create or update).\n"
             "Odoo only → local contact, never synced to Bokio.",
    )
    bokio_contact_type = fields.Char(
        string="Kontexttyp",
        index=True,
        copy=False,
        help="Synkdestination för denna kontakt: 'jessica', 'peter', 'aiab' m.fl.\n"
             "Sätts automatiskt vid synk. Admin kan ändra manuellt.",
    )

    def _register_hook(self):
        super()._register_hook()
        self._sync_bokio_contacts_menu_visibility()

    @api.model
    def _sync_bokio_contacts_menu_visibility(self):
        """Scope the stock Contacts app to admins only when this database is
        scoped to a single Bokio context (bokio.sync.contact_type set, e.g.
        konfident) — regular internal users (e.g. Jessica) then only see the
        dedicated Bokio Kontakter app instead. Unscoped databases (e.g. aiab)
        keep the stock Contacts app's normal visibility.

        Note: this is per-USER (via group_ids), not per-database "active" —
        an earlier version toggled active=False, which hid Contacts from
        every user including admins. ir.ui.menu.group_ids is an allow-list
        (OR'd), so to exclude a plain internal user (group_user) while still
        including admins (group_system, who are also group_user), the stock
        group_user/group_partner_manager entries must be replaced with just
        group_system — adding group_system alongside them would not exclude
        anyone, since Jessica still matches group_user via OR.

        Runs on every registry load (container start, module upgrade) so it
        always reflects the current system parameter — no per-database XML
        needed since this module's code is shared across databases.
        """
        contact_type = self.env['ir.config_parameter'].sudo().get_param(
            'bokio.sync.contact_type', ''
        ).strip().lower()
        scoped = bool(contact_type)
        stock_contacts_menu = self.env.ref('contacts.menu_contacts', raise_if_not_found=False)
        bokio_contacts_root = self.env.ref(
            'partner_bokio.menu_bokio_contacts_root', raise_if_not_found=False
        )
        if stock_contacts_menu:
            if not stock_contacts_menu.active:
                stock_contacts_menu.sudo().active = True
            if scoped:
                admin_group = self.env.ref('base.group_system')
                desired_ids = {admin_group.id}
            else:
                user_group = self.env.ref('base.group_user')
                creation_group = self.env.ref(
                    'base.group_partner_manager', raise_if_not_found=False
                )
                desired_ids = {user_group.id} | ({creation_group.id} if creation_group else set())
            if set(stock_contacts_menu.group_ids.ids) != desired_ids:
                stock_contacts_menu.sudo().group_ids = [Command.set(list(desired_ids))]
        if bokio_contacts_root and bokio_contacts_root.active != scoped:
            bokio_contacts_root.sudo().active = scoped

    @api.model
    def action_open_bokio_contacts(self):
        """Open a Contacts list scoped to this database's Bokio contact type.

        Reads system parameter bokio.sync.contact_type (same one the invoice
        sync uses to route contacts, e.g. 'jessica'). Empty param means this
        database isn't scoped to a single context (e.g. aiab19e) — show all.
        """
        contact_type = self.env['ir.config_parameter'].sudo().get_param(
            'bokio.sync.contact_type', ''
        ).strip().lower()
        domain = [('bokio_contact_type', '=', contact_type)] if contact_type else []
        context = {'default_bokio_contact_type': contact_type} if contact_type else {}
        return {
            'type': 'ir.actions.act_window',
            'name': 'Bokio kontakter',
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': domain,
            'context': context,
        }

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
        linked = 0
        error_lines: list[str] = []

        # Build Bokio name index once (only needed for linking Bokio-mastered records)
        _bokio_index: dict | None = None

        def _get_bokio_index() -> dict:
            nonlocal _bokio_index
            if _bokio_index is None:
                all_custs = client.list_customers()
                _bokio_index = {
                    (c.get("name") or c.get("companyname") or "").strip().lower(): c
                    for c in all_custs
                    if (c.get("name") or c.get("companyname") or "").strip()
                }
            return _bokio_index

        for partner in self:
            name = (partner.name or "").strip()
            if not name:
                skipped += 1
                continue

            # ── Odoo only: never touch Bokio at all. ─────────────────────────
            if partner.bokio_master == "none":
                skipped += 1
                continue

            # ── Bokio is master: pull Bokio data → Odoo. ─────────────────────
            # Step 1: ensure we have a bokio_id (link by name if missing).
            if partner.bokio_master == "bokio":
                current_bokio_id = partner.bokio_id
                if not current_bokio_id:
                    try:
                        idx = _get_bokio_index()
                        match = idx.get(name.lower())
                        if match:
                            current_bokio_id = (
                                match.get("id") or match.get("customerId") or ""
                            )
                            if current_bokio_id:
                                partner.write({"bokio_id": current_bokio_id})
                                linked += 1
                            else:
                                skipped += 1
                                continue
                        else:
                            skipped += 1
                            continue
                    except BokioAPIError as exc:
                        error_lines.append(f"{name} (link): {exc}")
                        errors += 1
                        continue

                # Step 2: fetch from Bokio and write to Odoo.
                try:
                    bokio_data = client.get_customer(current_bokio_id)
                    vals: dict = {}

                    contacts = bokio_data.get("contactsDetails", [])
                    default_contact = next(
                        (c for c in contacts if c.get("isDefault")),
                        contacts[0] if contacts else {},
                    )
                    email = (default_contact.get("email") or "").strip()
                    phone = (default_contact.get("phone") or "").strip()
                    if email:
                        vals["email"] = email
                    if phone:
                        vals["phone"] = phone

                    # Address is nested under "address" key in Bokio response
                    address = bokio_data.get("address") or {}
                    if address.get("line1"):
                        vals["street"] = address["line1"]
                    if address.get("line2"):
                        vals["street2"] = address["line2"]
                    if address.get("postalCode"):
                        vals["zip"] = address["postalCode"]
                    if address.get("city"):
                        vals["city"] = address["city"]

                    country_code = (address.get("country") or "").strip().upper()
                    if country_code:
                        country_rec = partner.env["res.country"].search(
                            [("code", "=", country_code)], limit=1
                        )
                        if country_rec:
                            vals["country_id"] = country_rec.id

                    vals["bokio_synced_at"] = fields.Datetime.now()
                    partner.write(vals)
                    updated += 1
                except BokioAPIError as exc:
                    error_lines.append(f"{name} (fetch): {exc}")
                    errors += 1
                continue

            # ── Odoo is master: push Odoo data to Bokio. ─────────────────────
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
        summary = f"Created: {created}  Updated: {updated}  Linked: {linked}  Skipped: {skipped}"
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
