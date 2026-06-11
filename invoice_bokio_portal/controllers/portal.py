import datetime

from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

STATUS_LABELS = {
    'draft': 'Utkast',
    'published': 'Skickad',
    'paid': 'Betald',
    'overdue': 'Förfallen',
    'overPaid': 'Överbetald',
    'credited': 'Krediterad',
}

STATUS_BADGE = {
    'draft': 'secondary',
    'published': 'primary',
    'paid': 'success',
    'overdue': 'danger',
    'overPaid': 'info',
    'credited': 'warning',
}


def _invoice_subtext(env):
    """Compute dynamic subtext for portal home card."""
    Invoice = env['bokio.invoice']
    today = datetime.date.today()

    overdue = Invoice.search([('bokio_status', '=', 'overdue')])
    unpaid = Invoice.search(
        [('bokio_status', '=', 'published')], order='due_date asc'
    )

    if not overdue and not unpaid:
        return 'Alla fakturor betalda'

    if overdue:
        n = len(overdue)
        return ('1 förfallen faktura' if n == 1
                else f'{n} förfallna fakturor')

    nearest = unpaid[0]
    n = len(unpaid)
    word = 'faktura' if n == 1 else 'fakturor'

    if not nearest.due_date:
        return f'{n} obetald {word}'

    delta = (nearest.due_date - today).days
    if delta < 0:
        return f'{n} förfallen {word}'
    if delta == 0:
        return f'{n} {word} förfaller idag'
    if delta == 1:
        return f'{n} {word} — förfaller imorgon'
    return f'{n} {word} — förfaller om {delta} dagar'


class BokioInvoicePortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'bokio_invoice_count' in counters:
            values['bokio_invoice_count'] = request.env['bokio.invoice'].search_count([])
        values['bokio_invoice_subtext'] = _invoice_subtext(request.env)
        return values

    @http.route('/my/bokio-invoices', type='http', auth='user', website=True)
    def portal_bokio_invoices(self, page=1, **kw):
        Invoice = request.env['bokio.invoice']
        invoice_count = Invoice.search_count([])
        pager = portal_pager(
            url='/my/bokio-invoices',
            total=invoice_count,
            page=page,
            step=20,
        )
        invoices = Invoice.search([], order='issue_date desc', limit=20, offset=pager['offset'])
        values = self._prepare_portal_layout_values()
        values.update({
            'invoices': invoices,
            'pager': pager,
            'page_name': 'bokio_invoices',
            'status_labels': STATUS_LABELS,
            'status_badge': STATUS_BADGE,
        })
        return request.render('invoice_bokio_portal.portal_my_bokio_invoices', values)

    @http.route('/my/bokio-invoices/<int:invoice_id>', type='http', auth='user', website=True)
    def portal_bokio_invoice_detail(self, invoice_id, **kw):
        invoices = request.env['bokio.invoice'].search([('id', '=', invoice_id)])
        if not invoices:
            return request.not_found()
        values = self._prepare_portal_layout_values()
        values.update({
            'invoice': invoices[0],
            'page_name': 'bokio_invoices',
            'status_labels': STATUS_LABELS,
            'status_badge': STATUS_BADGE,
        })
        return request.render('invoice_bokio_portal.portal_bokio_invoice_detail', values)

    @http.route('/my/bokio-invoices/<int:invoice_id>/pdf', type='http', auth='user', website=True)
    def portal_bokio_invoice_pdf(self, invoice_id, **kw):
        invoices = request.env['bokio.invoice'].search([('id', '=', invoice_id)])
        if not invoices or not invoices[0].has_pdf:
            return request.not_found()
        invoice = invoices[0]
        attachment = request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'bokio.invoice'),
            ('res_id', '=', invoice.id),
            ('mimetype', '=', 'application/pdf'),
        ], limit=1)
        if not attachment:
            return request.not_found()
        return request.make_response(
            attachment.raw,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', 'inline; filename="{}"'.format(attachment.name)),
            ],
        )


class ArvasPortalCustom(CustomerPortal):
    """Remove phone from mandatory fields and other ARVAS portal customizations."""

    def _get_mandatory_billing_address_fields(self, country_sudo):
        fields = super()._get_mandatory_billing_address_fields(country_sudo)
        fields.discard('phone')
        return fields

    def _get_mandatory_delivery_address_fields(self, country_sudo):
        fields = super()._get_mandatory_delivery_address_fields(country_sudo)
        fields.discard('phone')
        return fields
