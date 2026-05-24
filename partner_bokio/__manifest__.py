{
    "name": "Bokio Partner Connector",
    "version": "19.0.1.0.0",
    "summary": "Synchronise res.partner with Bokio customers — stores Bokio ID, customer number and sync status",
    "author": "Arvas International AB",
    "license": "LGPL-3",
    "category": "Contacts",
    "depends": ["contacts"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_partner_views.xml",
        "views/bokio_sync_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
}
