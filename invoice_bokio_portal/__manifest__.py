{
    "name": "Bokio Invoice Portal",
    "version": "19.0.1.0.0",
    "summary": "Portal access to Bokio invoices for customers",
    "author": "Arvas International AB",
    "website": "https://github.com/08arvasi/odoo_bokio_api/tree/19.0/invoice_bokio_portal",
    "license": "LGPL-3",
    "category": "Invoicing",
    "depends": ["invoice_bokio", "portal"],
    "data": [
        "security/ir.model.access.csv",
        "security/bokio_portal_rules.xml",
        "views/portal_templates.xml",
            "views/portal_address_overrides.xml",
    ],
    "installable": True,
    "application": False,
}
