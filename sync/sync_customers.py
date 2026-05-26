"""
sync_customers.py — Synkar kunder från Odoo 19 till Bokio.

Upsert-prioritet:
  1. Partner med ref = "bokio-{id}" → uppdatera via känt Bokio-ID
  2. Namn matchar befintlig Bokio-kund → uppdatera + sätt ref
  3. Ny kund → skapa i Bokio + sätt ref

Körning:
    python sync/sync_customers.py                    # live, aiab19_migrated
    python sync/sync_customers.py --dry-run          # ingen skrivning
    python sync/sync_customers.py --limit 5          # testa med 5 poster
    python sync/sync_customers.py --db aiab          # annan Odoo-db
    python sync/sync_customers.py --skip-update      # bara skapa, aldrig uppdatera
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Läs .env från clio-tools (två nivåer upp om vi kör från sync/)
_HERE = Path(__file__).resolve().parent
for _candidate in [_HERE.parent / ".env", _HERE.parent.parent / "clio-tools" / ".env"]:
    if _candidate.exists():
        load_dotenv(_candidate, override=False)
        break

sys.path.insert(0, str(_HERE.parent))
from bokio_api import BokioClient, BokioAPIError

# clio_odoo finns i clio-tools
_CLIO_TOOLS = _HERE.parent.parent / "clio-tools"
if _CLIO_TOOLS.exists():
    sys.path.insert(0, str(_CLIO_TOOLS))

REF_PREFIX = "bokio-"

ODOO_FIELDS = [
    "name", "email", "phone",
    "street", "street2", "zip", "city", "country_id",
    "vat", "is_company", "personnummer",
    "bokio_id", "bokio_master",           # från partner_bokio-modulen
    "ref",                                 # fallback om modulen ej installerad
]


def _norm(name: str | None) -> str:
    return (name or "").strip().lower()


def fetch_odoo_customers(db: str | None, limit: int | None) -> list[dict]:
    try:
        from clio_odoo import connect
    except ImportError:
        sys.exit("clio_odoo saknas — lägg till clio-tools i PYTHONPATH.")

    env_db = db or os.environ.get("ODOO_DB", "aiab19")
    conn = connect(db=env_db)
    Partner = conn["res.partner"]

    # Försök med customer_rank (kräver account-modulen), annars alla aktiva kontakter
    try:
        domain = [("customer_rank", ">", 0), ("active", "=", True), ("type", "=", "contact")]
        partners = Partner.search_read(domain, ODOO_FIELDS, limit=limit or 0)
    except Exception as e:
        if "customer_rank" in str(e):
            print("  [INFO] customer_rank saknas — hämtar alla aktiva kontakter istället")
            domain = [("active", "=", True), ("type", "=", "contact"), ("id", ">", 4)]
            fields = [f for f in ODOO_FIELDS if f != "personnummer"]
            try:
                partners = Partner.search_read(domain, ODOO_FIELDS, limit=limit or 0)
            except Exception:
                partners = Partner.search_read(domain, fields, limit=limit or 0)
        else:
            raise
    return partners


def build_bokio_index(client: BokioClient) -> dict[str, dict]:
    """Returnerar {name_normalized: bokio_customer}."""
    try:
        customers = client.list_customers()
    except BokioAPIError as e:
        sys.exit(f"Kunde inte hämta Bokio-kunder: {e}")
    return {
        key: c
        for c in customers
        if (key := _norm(c.get("name") or c.get("companyname")))
    }


def bokio_id_from_customer(cust: dict) -> str | None:
    return cust.get("id") or cust.get("customerId")


def write_bokio_id_to_odoo(conn, partner_id: int, bokio_id: str, dry_run: bool) -> None:
    if dry_run:
        return
    Partner = conn["res.partner"]
    # Write to bokio_id if partner_bokio module is installed, otherwise fall back to ref
    try:
        Partner.write([partner_id], {"bokio_id": bokio_id})
    except Exception:
        Partner.write([partner_id], {"ref": f"{REF_PREFIX}{bokio_id}"})


def sync(args: argparse.Namespace) -> None:
    dry_run = args.dry_run
    skip_update = args.skip_update

    token = os.environ.get("BOKIO_TOKEN")
    company_id = os.environ.get("BOKIO_COMPANY_ID")
    if not token or not company_id:
        sys.exit("BOKIO_TOKEN och BOKIO_COMPANY_ID måste sättas i .env")

    client = BokioClient(token=token, company_id=company_id)

    print("Hämtar Bokio-kunder…")
    bokio_index = build_bokio_index(client)
    print(f"  {len(bokio_index)} kunder i Bokio")

    print("Hämtar Odoo-kunder…")
    partners = fetch_odoo_customers(args.db, args.limit)
    print(f"  {len(partners)} kunder i Odoo\n")

    created = updated = skipped = errors = 0

    # Importera connect igen för ref-skrivning
    try:
        from clio_odoo import connect
        odoo_conn = connect(db=args.db or os.environ.get("ODOO_DB", "aiab19"))
    except ImportError:
        odoo_conn = None

    for p in partners:
        name = (p.get("name") or "").strip()
        if not name:
            print(f"  [SKIP] id={p['id']} — tomt namn")
            skipped += 1
            continue

        # Respektera bokio_master: hoppa poster där Bokio eller ingen är master
        bokio_master = p.get("bokio_master") or "odoo"
        if bokio_master in ("bokio", "none"):
            skipped += 1
            continue

        country_raw = p.get("country_id")
        country = country_raw[1] if isinstance(country_raw, (list, tuple)) and len(country_raw) > 1 else "SE"

        org_number = None
        if p.get("is_company"):
            org_number = p.get("vat") or None
        else:
            org_number = p.get("personnummer") or None

        payload = BokioClient.build_payload(
            name=name,
            is_company=bool(p.get("is_company")),
            org_number=org_number,
            vat=p.get("vat") if p.get("is_company") else None,
            street=p.get("street"),
            street2=p.get("street2"),
            zip_code=p.get("zip"),
            city=p.get("city"),
            country=country,
            email=p.get("email"),
            phone=p.get("phone"),
        )

        # Prefer dedicated bokio_id field (partner_bokio module); fall back to ref
        ref = p.get("ref") or ""
        bokio_id: str | None = p.get("bokio_id") or None
        if not bokio_id:
            if ref.startswith(REF_PREFIX):
                bokio_id = ref[len(REF_PREFIX):]

        # 2. Namnmatchning
        if not bokio_id:
            existing = bokio_index.get(_norm(name))
            if existing:
                bokio_id = bokio_id_from_customer(existing)

        try:
            if bokio_id and not skip_update:
                if not dry_run:
                    try:
                        client.update_customer(bokio_id, payload)
                    except BokioAPIError as e:
                        if e.status_code in (404, 405):
                            print(f"  [WARN] update ej stödd för {name} ({e}) — hoppar uppdatering")
                            skipped += 1
                            continue
                        raise
                print(f"  [OK]  Uppdaterad: {name} ({REF_PREFIX}{bokio_id})")
                updated += 1
                if odoo_conn and not ref.startswith(REF_PREFIX):
                    write_bokio_id_to_odoo(odoo_conn, p["id"], bokio_id, dry_run)
            elif bokio_id and skip_update:
                print(f"  [SKIP] Finns redan: {name}")
                skipped += 1
            else:
                if not dry_run:
                    result = client.create_customer(payload)
                    bokio_id = bokio_id_from_customer(result) or "?"
                    if odoo_conn:
                        write_bokio_id_to_odoo(odoo_conn, p["id"], bokio_id, dry_run)
                else:
                    bokio_id = "dry-run"
                print(f"  [OK]  Skapad:    {name} ({REF_PREFIX}{bokio_id})")
                created += 1
        except BokioAPIError as e:
            print(f"  [FEL] {name}: {e}")
            errors += 1

    mode = " (DRY-RUN)" if dry_run else ""
    print(f"\n{'─'*50}")
    print(f"Totalt: {len(partners)} kunder{mode}")
    print(f"  Skapade:    {created}")
    print(f"  Uppdaterade: {updated}")
    print(f"  Hoppade:    {skipped}")
    if errors:
        print(f"  Fel:        {errors}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Synka Odoo-kunder till Bokio")
    parser.add_argument("--dry-run", action="store_true", help="Ingen skrivning")
    parser.add_argument("--limit", type=int, default=None, metavar="N", help="Max antal Odoo-kunder")
    parser.add_argument("--db", default=None, help="Odoo-databas (default: aiab19_migrated)")
    parser.add_argument("--skip-update", action="store_true", help="Skapa bara nya, uppdatera aldrig")
    args = parser.parse_args()
    sync(args)


if __name__ == "__main__":
    main()
