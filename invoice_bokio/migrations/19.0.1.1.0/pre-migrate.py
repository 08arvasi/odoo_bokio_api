def migrate(cr, version):
    cr.execute("""
        ALTER TABLE bokio_invoice
        ALTER COLUMN bokio_invoice_number
        TYPE INTEGER USING NULLIF(bokio_invoice_number, '')::INTEGER
    """)
