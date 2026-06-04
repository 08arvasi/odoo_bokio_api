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


class BokioInvoicePortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'bokio_invoice_count' in counters:
            values['bokio_invoice_count'] = request.env['bokio.invoice'].search_count([])
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
