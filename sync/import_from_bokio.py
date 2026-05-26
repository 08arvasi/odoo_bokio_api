"""
import_from_bokio.py — Importerar alla kunder från Bokio till Odoo som res.partner.

Varje partner skapas med bokio_master='bokio' så att framtida synk hämtar
data från Bokio (aldrig skriver till Bokio).

Körning:
    python sync/import_from_bokio.py                      # live, aiab19b
    python sync/import_from_bokio.py --dry-run            # ingen skrivning
    python sync/import_from_bokio.py --limit 5            # testa 5 poster
    python sync/import_from_bokio.py --db aiab19          # annan Odoo-db
    python sync/import_from_bokio.py --skip-existing      # hoppa om bokio_id redan finns
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).resolve().parent
for _candidate in [_HERE.parent / ".env", _HERE.parent.parent / "clio-tools" / ".env"]:
    if _candidate.exists():
        load_dotenv(_candidate, override=False)
        break

sys.path.insert(0, str(_HERE.parent))
from bokio_api import BokioClient, BokioAPIError

_CLIO_TOOLS = _HERE.parent.parent / "clio-tools"
if _CLIO_TOOLS.exists():
    sys.path.insert(0, str(_CLIO_TOOLS))


def _country_id(env, code: str | None) -> int | None:
    if not code:
        return None
    result = env["res.country"].search_read(
        [("code", "=", code.strip().upper())], ["id"], limit=1
    )
    return result[0]["id"] if result else None


def build_odoo_vals(bokio_data: dict, env) -> dict:
    """Konverterar ett Bokio-kundobjekt till res.partner-värden."""
    name = (
        bokio_data.get("companyname")
        or bokio_data.get("name")
        or ""
    ).strip()
    is_company = bokio_data.get("type", "").lower() == "company"

    vals: dict = {
        "name": name,
        "is_company": is_company,
        "bokio_id": bokio_data.get("id") or bokio_data.get("customerId") or "",
        "bokio_master": "bokio",
        "customer_rank": 1,
    }

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
        cid = _country_id(env, country_code)
        if cid:
            vals["country_id"] = cid

    org_number = (bokio_data.get("orgNumber") or "").strip()
    if org_number and is_company:
        vals["vat"] = org_number

    return vals


def run(args: argparse.Namespace) -> None:
    dry_run = args.dry_run
    skip_existing = args.skip_existing

    token = os.environ.get("BOKIO_TOKEN")
    company_id = os.environ.get("BOKIO_COMPANY_ID")
    if not token or not company_id:
        sys.exit("BOKIO_TOKEN och BOKIO_COMPANY_ID måste sättas i .env")

    odoo_db = args.db or os.environ.get("ODOO_DB", "aiab19b")

    try:
        from clio_odoo import connect
    except ImportError:
        sys.exit("clio_odoo saknas — lägg till clio-tools i PYTHONPATH.")

    client = BokioClient(token=token, company_id=company_id)

    print("Hämtar kundlista från Bokio…")
    try:
        customers = client.list_customers()
    except BokioAPIError as e:
        sys.exit(f"Fel vid hämtning av Bokio-kunder: {e}")

    if args.limit:
        customers = customers[: args.limit]

    print(f"  {len(customers)} kunder att importera\n")

    conn = connect(db=odoo_db)
    Partner = conn["res.partner"]

    # Bygg index över befintliga bokio_id i Odoo
    existing_ids: set[str] = set()
    try:
        existing = Partner.search_read(
            [("bokio_id", "!=", False)], ["bokio_id"], limit=0
        )
        existing_ids = {r["bokio_id"] for r in existing if r.get("bokio_id")}
    except Exception:
        pass  # fältet kanske saknas om modulen inte är installerad

    created = updated = skipped = errors = 0

    for cust in customers:
        bokio_uuid = cust.get("id") or cust.get("customerId") or ""
        cust_name = (
            cust.get("companyname") or cust.get("name") or f"id={bokio_uuid}"
        ).strip()

        if not bokio_uuid:
            print(f"  [SKIP] {cust_name} — inget Bokio-ID")
            skipped += 1
            continue

        if skip_existing and bokio_uuid in existing_ids:
            print(f"  [SKIP] {cust_name} — redan importerad")
            skipped += 1
            continue

        # Hämta full kunddata (adress, kontakter)
        try:
            full_data = client.get_customer(bokio_uuid)
        except BokioAPIError as e:
            print(f"  [FEL]  {cust_name}: kan inte hämta detaljer — {e}")
            errors += 1
            continue

        try:
            vals = build_odoo_vals(full_data, conn)
        except Exception as e:
            print(f"  [FEL]  {cust_name}: fältmappning misslyckades — {e}")
            errors += 1
            continue

        if not vals.get("name"):
            print(f"  [SKIP] {cust_name} — tomt namn efter mappning")
            skipped += 1
            continue

        if dry_run:
            print(f"  [DRY]  {vals['name']} (bokio_id={bokio_uuid})")
            created += 1
            continue

        try:
            if bokio_uuid in existing_ids:
                # Uppdatera befintlig
                recs = Partner.search_read(
                    [("bokio_id", "=", bokio_uuid)], ["id"], limit=1
                )
                if recs:
                    Partner.write([recs[0]["id"]], vals)
                    print(f"  [OK]  Uppdaterad: {vals['name']}")
                    updated += 1
            else:
                Partner.create(vals)
                existing_ids.add(bokio_uuid)
                print(f"  [OK]  Skapad:    {vals['name']}")
                created += 1
        except Exception as e:
            print(f"  [FEL]  {vals.get('name', cust_name)}: {e}")
            errors += 1

    mode = " (DRY-RUN)" if dry_run else ""
    print(f"\n{'─'*50}")
    print(f"Bokio → Odoo ({odoo_db}){mode}")
    print(f"  Skapade:     {created}")
    print(f"  Uppdaterade: {updated}")
    print(f"  Hoppade:     {skipped}")
    if errors:
        print(f"  Fel:         {errors}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Importera Bokio-kunder till Odoo")
    parser.add_argument("--dry-run", action="store_true", help="Ingen skrivning")
    parser.add_argument("--limit", type=int, default=None, metavar="N")
    parser.add_argument("--db", default=None, help="Odoo-databas (default: aiab19b)")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Hoppa poster som redan har ett bokio_id i Odoo",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
