# invoice_bokio_portal — CLAUDE.md

Portalmodul för Odoo 19 som låter portalanvändare se och ladda ner sina Bokio-fakturor.

## Beroenden
- `invoice_bokio` — synkmodul (bokio.invoice-modellen)
- `portal` — Odoos standard-portalmodul
- **Inte** `website` — modulen fungerar utan den

## Åtkomstnivåer
- **Portalanvändare** — ser egna fakturor (`partner_id = user.partner_id`)
- **Kontakter kopplade till företag** — ser företagets fakturor (`partner_id.parent_id`)
- **Admin/interna användare** — ser alla fakturor (record rule gäller bara `base.group_portal`)

## Filer
```
invoice_bokio_portal/
├── controllers/
│   └── portal.py           # Rutter + _prepare_home_portal_values
├── security/
│   ├── bokio_portal_rules.xml      # Record rule för portalanvändare
│   └── ir.model.access.csv         # Läsrättighet för portal-gruppen
├── static/src/img/
│   └── portal-invoices.svg         # Ikon (80×80, lila #714B67 + guld #C8A84B)
└── views/
    ├── portal_templates.xml        # Startsida, listvy, detaljvy
    └── portal_address_overrides.xml # Döljer VAT, gör ikoner synliga, telefon valfritt
```

## Vyer
- `/my` — portalsida: fakturatile med dynamisk subtext och SVG-ikon
- `/my/bokio-invoices` — listvy, klickbara rader, PDF öppnas i nytt fönster
- `/my/bokio-invoices/<id>` — detaljvy med inline PDF-iframe
- `/my/bokio-invoices/<id>/pdf` — streamas direkt från ir.attachment

## Dynamisk subtext på startsidan
`_invoice_subtext()` i controllern beräknar text baserat på fakturastatus:
- `Alla fakturor betalda`
- `N förfallna fakturor`
- `N fakturor — förfaller om X dagar`

**OBS:** subtext läggs bara till när `counters=[]` (full sidrenderning), inte vid
AJAX-anrop till `/my/counters` — annars kraschar Odoos JS-counter-loader.

## Viktiga designbeslut
- **PDF-säkerhet:** `search()` med record rule verifierar åtkomst, sedan `sudo()` på
  `ir.attachment` (säkert eftersom invoice.id kommer från ORM, inte användarinput)
- **Ikonsynlighet:** `portal_docs_entry_layout` kräver `website`-modulen. Vi inkluderar
  egen `portal_icon_visible`-template (utan `customize_show`) i `portal_address_overrides.xml`
- **Adressformat:** partners från Bokio-sync utan landkod får Sverige (`SE`) som default
  så postnummer visas korrekt (187 72 Täby, inte Täby 187 72)
- **Portalformuläret:** telefon är valfritt, skattenummer dolt (override via XPath)

## Uppgradera
```bash
docker exec odoo19-odoo-1 odoo -d konfident --stop-after-init -u invoice_bokio_portal
docker restart odoo19-odoo-1
```
