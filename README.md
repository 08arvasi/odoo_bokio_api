# odoo_bokio_api

Återanvändbar Python-klient för Bokio REST API, med sync-skript för Odoo 19.

## Installation

```bash
pip install -e .
```

## Användning som bibliotek

```python
from bokio_api import BokioClient

client = BokioClient(token="...", company_id="...")
customers = client.list_customers()
new = client.create_customer(BokioClient.build_payload(
    name="Företaget AB",
    is_company=True,
    org_number="556123-4567",
    email="info@foretaget.se",
))
```

## Sync: Odoo → Bokio

```bash
cp .env.example .env   # fyll i BOKIO_TOKEN, BOKIO_COMPANY_ID, ODOO_*

python sync/sync_customers.py --dry-run --limit 5
python sync/sync_customers.py --limit 5
python sync/sync_customers.py
```

Kräver `clio_odoo` från [clio-tools](https://github.com/08arvasi/clio-tools).

## Konfiguration

Se `.env.example`.

## Miljö

Körs på EliteDesk GPU (`~/19.0/odoo_bokio_api/`).
