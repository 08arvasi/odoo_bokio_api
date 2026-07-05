# invoice_bokio — CLAUDE.md

Synkar fakturor från Bokio till `bokio.invoice`, laddar ner PDF:er och skickar
betalningsbekräftelser. Scopar fakturasynlighet per Bokio-kontext med en riktig
`ir.rule` (inte bara menyfiltrering).

## Konfiguration (Settings > Technical > System Parameters)
- `bokio.token`, `bokio.company_id` — Bokio-autentisering (faller tillbaka på
  env-variablerna `BOKIO_TOKEN`/`BOKIO_COMPANY_ID` om tomma)
- `bokio.sync.from_date` — startdatum för synk, default innevarande räkenskapsår
- `bokio.sync.filter_keyword` — filtrera fakturor på nyckelord i radtext (t.ex. `jessica`)
- `bokio.sync.contact_type` — vilken Bokio-kontext den här databasen tillhör
  (t.ex. `jessica` i konfident, tomt i aiab). Delas med `partner_bokio`.
- `bokio.mail.confirmation.enabled` — `1` för att skicka betalningsbekräftelse

## Behörighetsarkitektur (2026-07-05)
Två `ir.rule` på `bokio.invoice`, i `security/bokio_invoice_rules.xml`:

1. **`bokio_invoice_contact_type_rule`** (grupp `base.group_user`) — begränsar
   till fakturor vars kund har `bokio_contact_type = <bokio.sync.contact_type>`.
2. **`bokio_invoice_contact_type_admin_bypass_rule`** (grupp `base.group_system`) —
   alltid sant, ingen begränsning.

`base.group_system` **implicerar** `base.group_user`, och Odoo OR:ar regler
mellan alla grupper en användare tillhör. Utan regel 2 skulle admins (som också
är `group_user`) fastna i samma spärr som vanliga användare — bekräftat fel
2026-07-05 (fredrik@arvas.se nekades läsa exakt samma fakturor som Jessica).
Med båda reglerna: admins matchar regel 1 OCH 2 → OR blir alltid sant → obegränsat.
Jessica matchar bara regel 1 → scopad.

### Varför `domain_force` skrivs av `_register_hook`, inte statisk XML
`domain_force` är en statisk XML-sträng och kan inte läsa en systemparameter
direkt. Första försöket löste det med ett beräknat `bokio_visible`-fält
(`compute` + `search`) — **fungerade inte**: `check_access()` gav rätt svar,
men `search()` på samma post gav tomt resultat även för poster som borde
matcha. Trolig orsak: Odoo normaliserar regeldomänen `('bokio_visible','=',True)`
till `('bokio_visible','in',[True])` innan den når ett custom `search()`-fält,
och något i den översättningskedjan bröts mot hur `ir.rule` bygger den
faktiska SQL-frågan — aldrig fullt förklarat, men reproducerat och verifierat
(sökning läckte fel-kontext-fakturor OCH dolde rätt-kontext-fakturor samtidigt).

**Lösningen:** `BokioInvoice._register_hook()` → `_sync_bokio_invoice_context_rule()`
skriver kontexttypens värde **direkt in i `domain_force`** som en vanlig
relationsdomän (`[('partner_id.bokio_contact_type', '=', 'jessica')]`), ingen
custom fält-översättning inblandad. Körs vid varje registerladdning (containerstart,
`-u`), så den är alltid i synk med systemparametern utan databasspecifik XML.

**Testa alltid via `odoo shell` innan omstart** när denna metod ändras — verifiera
med både `.search([])` OCH `.browse(id).check_access('read')` för flera användare
(admin, Jessica), inte bara en av dem — det var precis skillnaden mellan de två
som avslöjade förra buggen.

## Filer
```
invoice_bokio/
├── models/
│   └── bokio_invoice.py         # Modell, synk, PDF, mail, _register_hook
├── security/
│   ├── ir.model.access.csv
│   └── bokio_invoice_rules.xml  # De två ir.rule ovan
├── data/
│   ├── mail_template.xml        # noupdate, betalningsbekräftelse-mall
│   ├── cron.xml
│   └── system_parameters.xml
└── views/
    ├── bokio_invoice_views.xml  # List/form/sök + action_bokio_invoice (ingen domän!)
    ├── bokio_sync_log_views.xml
    └── menus.xml                # Bokio > Invoices, Sync Log (eget top-menu, separat från partner_bokio:s Bokio Kontakter)
```

**OBS:** `action_bokio_invoice` (menyn "Bokio > Invoices") har ingen egen domän —
den förlitar sig helt på `ir.rule` för scoping. Det är avsiktligt: `ir.rule`
gäller alla vägar in (sök, lista, direkt-id), medan en menydomän bara skyddar
just den menyn.

## Uppgradera
```bash
docker exec odoo19-odoo-1 odoo -d konfident --stop-after-init -u invoice_bokio
docker restart odoo19-odoo-1
```
