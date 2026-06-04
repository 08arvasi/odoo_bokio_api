from odoo import fields, models


class BokioSyncLog(models.Model):
    _name = 'bokio.sync.log'
    _description = 'Bokio Sync Log'
    _order = 'sync_time desc'
    _rec_name = 'sync_time'

    sync_time = fields.Datetime(string='Sync Time', default=fields.Datetime.now, readonly=True)
    invoices_fetched = fields.Integer(string='Fetched', readonly=True)
    invoices_created = fields.Integer(string='Created', readonly=True)
    invoices_updated = fields.Integer(string='Updated', readonly=True)
    confirmations_sent = fields.Integer(string='Confirmations Sent', readonly=True)
    errors = fields.Text(string='Errors', readonly=True)
    status = fields.Selection([
        ('success', 'Success'),
        ('partial', 'Partial'),
        ('failed', 'Failed'),
    ], string='Status', default='success', readonly=True)
