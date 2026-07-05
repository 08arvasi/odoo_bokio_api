# partner_bokio — CLAUDE.md

Synkar `res.partner` med Bokio-kunder och scopar Kontakter-appen per Bokio-kontext
(t.ex. konfident/Jessica) utan att döljas för admins.

## Fält på res.partner
- `bokio_id`, `bokio_customer_number`, `bokio_synced_at` — synkstatus
- `bokio_master` — vem äger data (bokio/odoo/none)
- `bokio_contact_type` ("Kontexttyp") — vilken Bokio-kontext kontakten hör till
  (`jessica`, `peter`, `fredrik`, `niklas` m.fl.). Char-fält, ingen behörighetseffekt
  i sig själv — sätts automatiskt av `invoice_bokio._ensure_partner()` vid fakturasynk,
  **bara på nyskapade kontakter** (aldrig backfyllt på befintliga).

## Multi-kontext-arkitektur (2026-07-05)
Ett databasdelat kodbas (`konfident`, `aiab`, framtida `peter19`) behöver bete sig
olika beroende på om databasen är scopad till en enda Bokio-kontext eller inte:

- **Scopad databas** (systemparameter `bokio.sync.contact_type` satt, t.ex. `jessica`
  i `konfident`): vanliga interna användare (`base.group_user`, t.ex. Jessica) ska
  bara se sin egen kontexts kontakter. Admins (`base.group_system`, t.ex. fredrik)
  ska se allt, oavsett kontext.
- **Oscopad databas** (parametern tom, t.ex. `aiab`): alla beter sig som vanligt.

### `_register_hook` — `_sync_bokio_contacts_menu_visibility()`
Körs vid **varje** registerladdning (containerstart, `-u`) — inte bara install.
Läser `bokio.sync.contact_type` och:
- Sätter standardmenyns (`contacts.menu_contacts`) `group_ids` till **enbart**
  `base.group_system` om scopad, annars återställer originalgrupperna
  (`base.group_user` + `base.group_partner_manager`).
- Växlar `active` på vår egen app `menu_bokio_contacts_root` ("Bokio Kontakter").

**Varför inte `active=False` på standardmenyn:** det döljer den för *alla*
användare i databasen, inklusive admins — testat och bekräftat fel 2026-07-05
(fredrik såg bara "Bokio Kontakter", inte "Kontakter"). `group_ids` är en
vitlista (OR-logik) — kan inte uttrycka "alla utom Jessica", bara "exakt dessa
grupper". Lösningen: byt ut gruppkravet till enbart `group_system` när scopad,
eftersom `group_system` **implicerar** `group_user` (så admins matchar ändå),
men Jessica (bara `group_user`) matchar inte längre.

### Ny app: "Bokio Kontakter"
Ersätter standard-Kontakter-appen för icke-admin-användare i scopade databaser.
- `menu_bokio_contacts_root` — toppnivå-app (ingen `action`, som `contacts.menu_contacts`)
- `menu_partner_bokio_contacts` ("Bokio kontakter") → `action_open_bokio_contacts`
  (server action → `action_open_bokio_contacts()`-metoden, domän
  `[('bokio_contact_type','=', contact_type)]` om satt, annars tom = visa allt)
- `menu_partner_bokio_sync` ("Bokio Sync Status") → `action_open_bokio_sync_status`
  (samma mönster, bygger vidare på den statiska XML-actionen via `_for_xml_id`)

Båda actionerna bygger domänen **dynamiskt i Python vid varje anrop** — ingen
lagrad kopia, alltid i synk med systemparametern.

## Filer
```
partner_bokio/
├── models/
│   └── res_partner.py       # Fält + _register_hook + actions + Bokio-synk
├── data/
│   └── server_actions.xml   # action_open_bokio_contacts, action_open_bokio_sync_status
└── views/
    ├── menus.xml             # Bokio Kontakter-app + undermenyer
    ├── res_partner_views.xml # Sökfilter/gruppering på Kontexttyp
    └── bokio_sync_views.xml  # Bokio Sync Status kanban/list/sök + action_partner_bokio_sync
```

## Uppgradera
```bash
docker exec odoo19-odoo-1 odoo -d konfident --stop-after-init -u partner_bokio
docker restart odoo19-odoo-1
```

**Testa alltid via `odoo shell` innan omstart** när `_register_hook` ändras —
en trasig kodrad där kraschar hela registerladdningen för databasen (bekräftat
2026-07-05, fel Odoo-19-fältnamn `groups_id` istället för `group_ids` tog ner
`konfident` tills det rättades).
