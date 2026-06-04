{
    "name": "Bokio Invoice Sync",
    "version": "19.0.1.0.0",
    "summary": "Sync invoices from Bokio — payment confirmation on paid status",
    "description": """
Bokio Invoice Sync
==================
Synkar fakturor från Bokio till Odoo och skickar betalningsbekräftelser.

Konfiguration (Settings > Technical > System Parameters):
  bokio.token                      Bokio Private Integration Token
  bokio.company_id                 Bokio Company UUID
  bokio.sync.from_date             Startdatum för synk (YYYY-MM-DD).
                                   Default: innevarande räkenskapsår (1 sep).
                                   Ändra till t.ex. 2024-09-01 för föregående VÅ.
  bokio.mail.confirmation.enabled  Sätt till 1 för att aktivera mailutskick vid betalning.
    """,
    "author": "Arvas International AB",
    "license": "LGPL-3",
    "category": "Invoicing",
    "depends": ["contacts", "mail", "partner_bokio"],
    "data": [
        "security/ir.model.access.csv",
        "data/mail_template.xml",
        "data/cron.xml",
        "data/system_parameters.xml",
        "views/bokio_invoice_views.xml",
        "views/bokio_sync_log_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
}
