from __future__ import annotations

import base64
import json
import os
import sys
from datetime import date
from pathlib import Path

from odoo import api, fields, models
from odoo.exceptions import UserError

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


class BokioInvoice(models.Model):
    _name = 'bokio.invoice'
    _description = 'Bokio Invoice'
    _inherit = ['mail.thread']
    _order = 'issue_date desc, bokio_invoice_number desc'
    _rec_name = 'bokio_invoice_number'

    bokio_id = fields.Char(string='Bokio ID', required=True, copy=False, index=True)
    bokio_invoice_number = fields.Char(string='Invoice No.', copy=False)
    partner_id = fields.Many2one('res.partner', string='Customer', ondelete='set null', index=True)
    partner_email = fields.Char(
        related='partner_id.email',
        string='E-post',
        readonly=True,
        store=False,
    )
    amount_total = fields.Float(string='Total', digits=(12, 2))
    amount_tax = fields.Float(string='Tax', digits=(12, 2))
    amount_paid = fields.Float(string='Paid Amount', digits=(12, 2))
    currency = fields.Char(string='Currency', default='SEK')
    issue_date = fields.Date(string='Invoice Date')
    due_date = fields.Date(string='Due Date')
    published_at = fields.Datetime(string='Published At')
    bokio_status = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('overPaid', 'Overpaid'),
        ('credited', 'Credited'),
    ], string='Status', index=True)
    paid_detected_at = fields.Datetime(string='Paid Detected At', copy=False, readonly=True)
    confirmation_status = fields.Selection([
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('n_a', 'N/A — imported as paid'),
    ], string='Confirmation', default='pending', copy=False,
       help="pending: paid but confirmation not yet sent.\n"
            "sent: confirmation mail actually sent.\n"
            "N/A: invoice was already paid when first imported — no mail sent.")
    confirmation_sent_at = fields.Datetime(string='Confirmation Sent At', copy=False, readonly=True)
    has_pdf = fields.Boolean(string='PDF', default=False, copy=False)
    last_synced = fields.Datetime(string='Last Synced', readonly=True)
    bokio_visible = fields.Boolean(
        string='Synlig i denna Bokio-kontext',
        compute='_compute_bokio_visible',
        search='_search_bokio_visible',
        help="False if this invoice's customer belongs to a different Bokio "
             "context than this database's bokio.sync.contact_type. Backs "
             "the ir.rule that hides invoices from the wrong context.",
    )

    def _compute_bokio_visible(self):
        contact_type = self._get_contact_type()
        for invoice in self:
            partner_type = (invoice.partner_id.bokio_contact_type or '').strip().lower()
            invoice.bokio_visible = (not contact_type) or (partner_type == contact_type)

    @api.model
    def _search_bokio_visible(self, operator, value):
        """Translate a search on bokio_visible into a real partner_id domain.

        The ir.rule domain_force [('bokio_visible', '=', True)] doesn't
        necessarily reach us as operator='=' — Odoo's rule-combination logic
        normalizes it to operator='in', value=[True] before calling this
        method, and other callers may use '!=' / 'not in'. Handling only '='
        silently fell through to the negated (wrong-context) domain for
        every real-world call, which is exactly what leaked wrong-context
        invoices into Jessica's list (confirmed 2026-07-05).
        """
        contact_type = self._get_contact_type()
        if not contact_type:
            return []
        if operator in ('=', '!='):
            match_wanted = bool(value) if operator == '=' else not bool(value)
        elif operator in ('in', 'not in'):
            values = value if isinstance(value, (list, tuple, set)) else [value]
            match_wanted = (True in values) if operator == 'in' else (True not in values)
        else:
            raise ValueError(f"Unsupported operator {operator!r} for bokio_visible search")
        domain = [('partner_id.bokio_contact_type', '=', contact_type)]
        return domain if match_wanted else ['!'] + domain

    raw_json = fields.Text(string='Raw JSON')

    _unique_bokio_id = models.Constraint(
        'UNIQUE(bokio_id)',
        'A Bokio invoice ID must be unique.',
    )

    # ── Config helpers ─────────────────────────────────────────────────────────

    @api.model
    def _get_sync_from_date(self) -> str:
        """Return sync start date as 'YYYY-MM-DD'.

        Reads bokio.sync.from_date from Settings → Technical → System Parameters.
        If not set, calculates current fiscal year start (1 Sep, broken FY)
        and saves it as the default.
        """
        get_param = self.env['ir.config_parameter'].sudo().get_param
        from_date = get_param('bokio.sync.from_date')
        if not from_date:
            today = date.today()
            fy_year = today.year if today.month >= 9 else today.year - 1
            from_date = f'{fy_year}-09-01'
            self.env['ir.config_parameter'].sudo().set_param(
                'bokio.sync.from_date', from_date
            )
        return from_date

    @api.model
    def _get_bokio_client(self):
        from bokio_api import BokioClient
        get_param = self.env['ir.config_parameter'].sudo().get_param
        token = get_param('bokio.token') or os.environ.get('BOKIO_TOKEN', '')
        company_id = get_param('bokio.company_id') or os.environ.get('BOKIO_COMPANY_ID', '')
        if not token or not company_id:
            raise UserError(
                'bokio.token and bokio.company_id must be set in '
                'Settings > Technical > System Parameters'
            )
        return BokioClient(token=token, company_id=company_id)

    @api.model
    def _get_contact_type(self) -> str:
        """Return contact type tag for partners created during sync.

        System parameter: bokio.sync.contact_type
        Example value:    jessica
        Defaults to empty string (no tag set).
        """
        val = self.env['ir.config_parameter'].sudo().get_param(
            'bokio.sync.contact_type', ''
        )
        return (val or '').strip().lower()

    @api.model
    def _get_filter_keyword(self) -> str:
        """Return lowercase filter keyword, or '' to sync all invoices.

        System parameter: bokio.sync.filter_keyword
        Example value:    jessica
        Leave empty to import all invoices regardless of content.
        """
        kw = self.env['ir.config_parameter'].sudo().get_param(
            'bokio.sync.filter_keyword', ''
        )
        return (kw or '').strip().lower()

    @staticmethod
    def _invoice_matches_keyword(inv: dict, keyword: str) -> bool:
        """Return True if any lineItem description contains the keyword."""
        return any(
            keyword in (item.get('description') or '').lower()
            for item in inv.get('lineItems', [])
        )

    @api.model
    def _ensure_partner(self, client, customer_ref_id: str):
        """Return res.partner for the Bokio customer ID, creating on-demand if missing."""
        if not customer_ref_id:
            return self.env['res.partner']

        partner = self.env['res.partner'].search(
            [('bokio_id', '=', customer_ref_id)], limit=1
        )
        if partner:
            return partner

        # Not in Odoo yet — pull from Bokio and create with bokio_master='bokio'
        from bokio_api import BokioAPIError
        try:
            bokio_data = client.get_customer(customer_ref_id)
        except BokioAPIError:
            return self.env['res.partner']

        name = (bokio_data.get('companyname') or bokio_data.get('name') or '').strip()
        if not name:
            return self.env['res.partner']

        contact_type = self._get_contact_type()
        vals = {
            'name': name,
            'is_company': bokio_data.get('type', '').lower() == 'company',
            'bokio_id': customer_ref_id,
            'bokio_master': 'bokio',
            'bokio_synced_at': fields.Datetime.now(),
        }
        if contact_type:
            vals['bokio_contact_type'] = contact_type

        contacts = bokio_data.get('contactsDetails', [])
        default_contact = next(
            (c for c in contacts if c.get('isDefault')),
            contacts[0] if contacts else {},
        )
        email = (default_contact.get('email') or '').strip()
        phone = (default_contact.get('phone') or '').strip()
        if email:
            vals['email'] = email
        if phone:
            vals['phone'] = phone

        address = bokio_data.get('address') or {}
        if address.get('line1'):
            vals['street'] = address['line1']
        if address.get('line2'):
            vals['street2'] = address['line2']
        if address.get('postalCode'):
            vals['zip'] = address['postalCode']
        if address.get('city'):
            vals['city'] = address['city']

        country_code = (address.get('country') or '').strip().upper()
        if country_code:
            country_rec = self.env['res.country'].search(
                [('code', '=', country_code)], limit=1
            )
            if country_rec:
                vals['country_id'] = country_rec.id
        else:
            se = self.env['res.country'].search([('code', '=', 'SE')], limit=1)
            if se:
                vals['country_id'] = se.id

        return self.env['res.partner'].create(vals)

    # ── PDF ────────────────────────────────────────────────────────────────────

    def _fetch_and_store_pdf(self, client) -> str | None:
        """Download PDF for this record and store as ir.attachment.
        Returns None on success, error string on failure, 'skip' if already present.
        """
        self.ensure_one()
        if self.has_pdf:
            return 'skip'
        try:
            pdf_bytes = client.download_invoice_pdf(self.bokio_id)
            fname = f'Faktura_{self.bokio_invoice_number}_{self.issue_date}.pdf'
            self.env['ir.attachment'].create({
                'name': fname,
                'datas': base64.b64encode(pdf_bytes).decode(),
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/pdf',
                'type': 'binary',
            })
            self.write({'has_pdf': True})
            return None
        except Exception as exc:
            return str(exc)

    def action_fetch_pdf(self):
        """Manual button: fetch PDF from Bokio for selected invoice(s)."""
        try:
            client = self._get_bokio_client()
        except Exception as exc:
            raise UserError(str(exc)) from exc

        done = skipped = failed = 0
        for record in self:
            result = record._fetch_and_store_pdf(client)
            if result == 'skip':
                skipped += 1
            elif result is None:
                done += 1
            else:
                failed += 1

        msg = f'Downloaded {done}'
        if skipped:
            msg += f' | Already present {skipped}'
        if failed:
            msg += f' | Failed {failed}'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Bokio PDF',
                'message': msg,
                'type': 'success' if not failed else 'warning',
            },
        }

    @api.model
    def action_fetch_missing_pdfs(self, batch_size=10):
        """Cron: hämtar PDFs för fakturor som saknar dem, max batch_size per körning."""
        records = self.search(
            [('has_pdf', '=', False), ('bokio_id', '!=', False), ('bokio_id', '!=', 'z')],
            limit=batch_size,
        )
        if not records:
            return
        try:
            client = self._get_bokio_client()
        except Exception:
            return
        done = failed = 0
        for record in records:
            result = record._fetch_and_store_pdf(client)
            if result is None:
                done += 1
            elif result != 'skip':
                failed += 1

    # ── Sync ───────────────────────────────────────────────────────────────────

    @api.model
    def action_sync_invoices(self):
        """Sync invoices from Bokio. Called by cron and manual server action."""
        try:
            from bokio_api import BokioAPIError
        except ImportError as exc:
            raise UserError(f'bokio_api package not found: {exc}') from exc

        try:
            client = self._get_bokio_client()
        except UserError:
            raise

        get_param = self.env['ir.config_parameter'].sudo().get_param
        fetched = created = updated = confirmations = 0
        error_lines: list[str] = []

        try:
            invoices = client.list_invoices()
        except BokioAPIError as exc:
            self.env['bokio.sync.log'].create({'status': 'failed', 'errors': str(exc)})
            raise UserError(f'Bokio API error: {exc}') from exc

        from_date = self._get_sync_from_date()
        invoices = [inv for inv in invoices if (inv.get('invoiceDate') or '') >= from_date]

        # ── Keyword filter ────────────────────────────────────────────────────
        # bokio.sync.filter_keyword: if set, only process invoices whose
        # lineItems contain the keyword. Credit notes that credit a matched
        # invoice are always included regardless of their own content.
        keyword = self._get_filter_keyword()
        if keyword:
            # Pass 1: collect matched IDs and their associated credit note IDs
            matched_ids: set[str] = set()
            credit_note_ids: set[str] = set()
            for inv in invoices:
                if self._invoice_matches_keyword(inv, keyword):
                    matched_ids.add(inv['id'])
                    for ref in inv.get('creditNoteRefs', []):
                        cid = ref.get('id') if isinstance(ref, dict) else str(ref)
                        if cid:
                            credit_note_ids.add(cid)
            # Pass 2: keep matched invoices + their credit notes
            invoices = [
                inv for inv in invoices
                if inv['id'] in matched_ids or inv['id'] in credit_note_ids
            ]

        fetched = len(invoices)
        now = fields.Datetime.now()
        mail_enabled = get_param('bokio.mail.confirmation.enabled') == '1'

        for inv in invoices:
            bokio_id = inv.get('id', '')
            if not bokio_id:
                continue
            try:
                existing = self.search([('bokio_id', '=', bokio_id)], limit=1)
                customer_ref_id = (inv.get('customerRef') or {}).get('id', '')
                # On-demand partner sync: create partner from Bokio if not in Odoo
                partner = self._ensure_partner(client, customer_ref_id)
                new_status = inv.get('status', '')
                old_status = existing.bokio_status if existing else None

                vals = {
                    'bokio_id': bokio_id,
                    'bokio_invoice_number': inv.get('invoiceNumber', ''),
                    'partner_id': partner.id if partner else False,
                    'amount_total': inv.get('totalAmount', 0.0),
                    'amount_tax': inv.get('totalTax', 0.0),
                    'amount_paid': inv.get('paidAmount', 0.0),
                    'currency': inv.get('currency', 'SEK'),
                    'issue_date': inv.get('invoiceDate'),
                    'due_date': inv.get('dueDate'),
                    'published_at': (inv.get('publishedDateTime') or '').replace('T', ' ').rstrip('Z') or False,
                    'bokio_status': new_status,
                    'last_synced': now,
                    'raw_json': json.dumps(inv, ensure_ascii=False),
                }

                is_new = not existing
                if existing:
                    if new_status == 'paid' and old_status != 'paid' and not existing.paid_detected_at:
                        vals['paid_detected_at'] = now
                    existing.write(vals)
                    record = existing
                    updated += 1
                else:
                    if new_status == 'paid':
                        vals['paid_detected_at'] = now
                        vals['confirmation_status'] = 'n_a'
                    record = self.create(vals)
                    created += 1

                # Send confirmation for live paid transitions
                if (
                    mail_enabled
                    and record.bokio_status == 'paid'
                    and record.confirmation_status == 'pending'
                    and record.partner_email
                ):
                    try:
                        template = self.env.ref(
                            'invoice_bokio.mail_template_payment_confirmation',
                            raise_if_not_found=False,
                        )
                        if template:
                            template.send_mail(record.id, force_send=True)
                            record.write({
                                'confirmation_status': 'sent',
                                'confirmation_sent_at': now,
                            })
                            confirmations += 1
                    except Exception as mail_exc:
                        error_lines.append(f'Mail {bokio_id}: {mail_exc}')

            except Exception as exc:
                error_lines.append(f'{bokio_id}: {exc}')

        status = 'success'
        if error_lines:
            status = 'partial' if (created + updated) > 0 else 'failed'

        self.env['bokio.sync.log'].create({
            'sync_time': now,
            'invoices_fetched': fetched,
            'invoices_created': created,
            'invoices_updated': updated,
            'confirmations_sent': confirmations,
            'errors': '\n'.join(error_lines) if error_lines else False,
            'status': status,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Bokio Sync',
                'message': (
                    f'Fetched {fetched} | Created {created} | '
                    f'Updated {updated} | Confirmations {confirmations}'
                ),
                'type': 'success' if status == 'success' else 'warning',
                'sticky': bool(error_lines),
            },
        }
