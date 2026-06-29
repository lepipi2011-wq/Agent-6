# Agent 6 — Engine

**Verifikations-first OEM-Discovery & -Verifikation** für kettengetriebene Maschinen
(Raupenfahrzeuge) als Kandidaten für Safety-Remote-Control-Upgrades.
Interne Software der **NBB Controls**.

> **Leitidee:** Die Datenbank ist die Wahrheitsquelle, der Master eine generierte
> Export-Sicht. Jede Aussage über einen OEM ist ein *Claim* mit Quelle, Confidence
> und Zeit. **Qualität vor Quantität** — verifiziert wird nur, was mehrere
> unabhängige Primärquellen bestätigen.

---

## Inhalt
1. [Was das ist](#was-das-ist)
2. [Architektur](#architektur)
3. [Der komplette Ablauf](#der-komplette-ablauf)
4. [Installation](#installation)
5. [CLI-Referenz](#cli-referenz)
6. [Konnektoren](#konnektoren)
7. [Bild-Harvester & VLM-Filter](#bild-harvester--vlm-filter)
8. [Konfiguration](#konfiguration)
9. [Projektstruktur](#projektstruktur)
10. [Tests & CI](#tests--ci)
11. [Datenmodell](#datenmodell)
12. [USA-Erweiterung](#usa-erweiterung)
13. [Stand & Roadmap](#stand--roadmap)
14. [Sicherheit](#sicherheit)

---

## Was das ist

Agent 6 industrialisiert die OEM-Recherche als **verifikations-first Entity-Plattform**,
nicht als Scraper. Statt manueller Batch-Suchen mit Urteil im Kopf entsteht ein
kanonischer Entity-Graph, in dem jede Firma eindeutig ist und jede Aussage ihre
Quelle trägt. Das behebt drei Schwächen der manuellen Arbeit: fehlende Provenienz,
stille Fehler (falsche Merges) und mangelnde Reproduzierbarkeit.

## Architektur

Vier Schichten plus Ops-Substrat:

1. **Quell-Konnektoren** — breite Abdeckung über Primär-/Open-Quellen.
2. **Ingestion + Entity-Resolution** — normalisieren, deduplizieren, kanonisieren über starke Schlüssel (LEI/VAT/HR).
3. **Kern (DB)** — kanonische Entitäten + Claims mit Provenienz + Klassifikation.
4. **Delivery** — Master-Export, Pipedrive/Clay, Dashboards.
5. **Orchestrierung & Ops** — Worker, CI, Monitoring, Cache, EU-Hosting.

Zwei Kreisläufe: **Verifikation** (Qualität) und **Application-Discovery** (neue Felder).
Ausführliche Beschreibung: [`docs/`](docs/) und das Architektur-Word-Dokument.

## Der komplette Ablauf

| # | Schritt | Befehl | Was passiert |
|---|---|---|---|
| 1 | Import | `pipeline import` | Master → DB; Entity-Resolution legt Entitäten an, flaggt unsichere Dubletten |
| 2 | Enrich | `pipeline enrich` | Primärquellen holen LEI/VAT/Attribute (Claims) |
| 3 | Re-Resolve | (in `enrich`) | Orgs mit gleichem starken Schlüssel werden **sicher** gemerged |
| 4 | Review | `pipeline review` | manuelle Merge-Entscheidungen aus dem xlsx zurückspielen |
| 5 | Export | `pipeline export` | Master-Sicht + Merge-Review als xlsx |

Nebenläufig: **Bild-Harvest** (speist die VLM-Klassifikation) und **Discovery**
(neue OEMs/Anwendungsfelder → zurück in den Import).

**Warum diese Reihenfolge zwingend ist:** Ohne starke Schlüssel lässt sich nichts
sicher automatisch deduplizieren — Namensähnlichkeit merged falsch und verliert
echte OEMs. Deshalb: erst Schlüssel holen (enrich), **dann** mergen (re-resolve),
Rest per Review.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e .                     # + optional: ".[dev]" (Tests), ".[vlm]" (Bild-Filter)
cp config.example.yaml config.yaml   # lokale Konfig (gitignored)
# in config.yaml: master.path und database.url setzen
```

Erststart:

```bash
python -m agent6_engine.pipeline init
python -m agent6_engine.pipeline import     # Checkpoint: 1158 Orgs, 230 Review, 1388 Claims
python -m agent6_engine.pipeline status
```

**SQLite → Postgres:** nur `database.url` auf `postgresql+psycopg://user:pass@host/agent6`
setzen, `pip install "psycopg[binary]"`, `init` erneut. Gleiche Befehle, gleiche Definition.

Voller Durchlauf in einem Befehl: `python -m agent6_engine.pipeline all`.

## CLI-Referenz

| Befehl | Zweck | Wichtige Flags |
|---|---|---|
| `init` | DB-Schema anlegen | — |
| `import` | Master → DB | — |
| `enrich` | Schlüssel holen + Re-Resolve | `--region eu\|us`, `--limit N`, `--dry` |
| `review` | Merge-Entscheidungen zurückspielen | `--file merge_review.xlsx` |
| `export` | Master-Sicht + Merge-Review | — |
| `status` | Kennzahlen (Orgs, LEI, Claims, offene Reviews) | — |
| `all` | init+import+enrich+export | wie `enrich` |

Alle Befehle: `--config config.yaml`. Der `agent6`-Konsolenbefehl (via
`pip install -e .`) ist ein Alias für `python -m agent6_engine.pipeline`.

## Konnektoren

Gratis-Primärquellen zuerst — kein teures SaaS. Volle Übersicht:
[`docs/CONNECTORS.md`](docs/CONNECTORS.md).

- **EU/DACH:** GLEIF (LEI), Companies House (UK), Wikidata, Impressum.
- **US:** GLEIF, SEC EDGAR (CIK), SAM.gov (UEI), USPTO PatentsView, FCC ID.
- **Validatoren:** VIES (VAT-Prüfung, kein Discovery).

`parse()` ist offline per pytest abgesichert; Live-Calls laufen auf deiner Maschine.

## Bild-Harvester & VLM-Filter

```bash
python -m agent6_engine.cli --config config.yaml --live --max-oems 25
```

- OEM-direkte Produktbilder, Klassen **P1…P16 + out_scope** (Adjacent/Exklusion
  wird via `normalize_class` zu `out_scope` zusammengeführt — keine Splitter-Klassen).
- Netzwerk-robust (www↔non-www, SSL-Fallback, http-Fallback), Größenfilter (< 300 px raus),
  pHash-Dedup, `sources.csv` mit Provenienz, Quality-Gate (Yield/OEM-direkt/Score).
- **VLM-Scope-Gate** (`harvest.vlm_filter: true`): prüft **jedes** Bild per Claude
  gegen seine Klasse und verwirft Turbinen/Loks/Hallen/Logos — der eigentliche Fix
  gegen semantisches Rauschen. Braucht `pip install ".[vlm]"` + `ANTHROPIC_API_KEY`.
  Ohne Key/Flag: fail-open (blockt nichts).

## Konfiguration

`config.example.yaml` → `config.yaml` kopieren. Zentrale Schlüssel:

```yaml
master:   { path: "agent6_master_live.xlsx" }
database: { url: "sqlite:///agent6.db" }        # Prod: postgresql+psycopg://...
harvest:
  dry_run: true          # false = echte Downloads
  normalize_classes: true
  vlm_filter: false       # true = VLM-Bildprüfung (braucht ANTHROPIC_API_KEY)
  min_image_px: 300
```

Secrets kommen aus **Umgebungsvariablen**, nicht aus der config:
`ANTHROPIC_API_KEY`, `COMPANIES_HOUSE_KEY`, `SAM_GOV_KEY`, `PATENTSVIEW_KEY`, `SERPAPI_KEY`.

## Projektstruktur

```
agent6-engine/
├── agent6_engine/
│   ├── db.py                 # Entity-Graph + Claims (SQLAlchemy)
│   ├── db_import.py          # Master -> DB
│   ├── db_export.py          # DB -> Master-Sicht + Merge-Review
│   ├── entity_resolution.py  # konservative ER, merge_orgs, reresolve
│   ├── enrich_keys.py        # Konnektoren über alle Orgs (EU/US) + Re-Resolve
│   ├── review_apply.py       # Merge-Entscheidungen aus xlsx zurückspielen
│   ├── verify.py             # Verifikations-Loop Pass 1 (Multi-Quellen)
│   ├── pipeline.py           # CLI: init/import/enrich/review/export/status/all
│   ├── connectors/           # GLEIF, VIES, CH, Wikidata, Impressum, EDGAR, SAM, PatentsView, FCC
│   ├── image_harvest.py      # OEM-direkter Bild-Harvester
│   ├── vlm_filter.py         # VLM-Scope-Gate (Bild gegen Klasse)
│   ├── master_io.py          # Master-Lesen + normalize_class
│   ├── quality_gate.py       # Batch-Metriken
│   └── cli.py                # Harvester-CLI
├── docs/                     # Anleitung, Phasen, Konnektoren
├── tests/                    # Offline-Tests (pytest)
├── config.example.yaml
└── pyproject.toml
```

## Tests & CI

```bash
pip install -e ".[dev]"
pytest -q                    # 7 Offline-Tests: Normalisierung, ER, VLM-Parser, Konnektoren, Review
```

Bei jedem Push laufen dieselben Tests in GitHub Actions (`.github/workflows/ci.yml`).

## Datenmodell

Entitäten: **Organization, Brand, Model, Pattern, Application, Contact, Source, Claim.**
Starke Schlüssel: **LEI (GLEIF), VAT (VIES), HR-/Registernummer** (US: LEI/UEI/CIK).
Entity-Resolution **konservativ**: Auto-Merge nur bei starken Schlüsseln oder norm-exakt;
schwache Treffer werden als Review-Kandidat protokolliert, nie still gemerged
(Präzision vor Recall).

## USA-Erweiterung

Architektur identisch — nur die Quell-Schicht wechselt (`enrich --region us`).
**Achtung:** kein zentrales Handelsregister (50 Bundesstaaten), kein VAT/VIES, keine
Impressumspflicht → geringere Stark-Schlüssel-Abdeckung, größerer Review-Anteil.
Besonderheit: **FCC-ID** belegt „Funk vorhanden“ direkt (gratis Primärquelle).

## Stand & Roadmap

**Gebaut & validiert:** DB-Kern, Import/Export, konservative ER + Merge-Log,
Konnektoren (EU + US + Impressum), Verifikation Pass 1, Review-Rückspielung,
Bild-Harvester inkl. Klassen-Normalisierung und VLM-Filter, Pipeline-CLI, Tests, CI.

**Geplant:** VLM-Scope-Gate als eigener Pipeline-Schritt, Discovery-Konnektoren
(Marktplätze/Messen/Patente), Prefect-Worker + Dashboards, 3CX-Transkription.

## Sicherheit

- Keine Secrets im Repo — `config.yaml` und `.env` sind gitignored; Keys über Umgebungsvariablen.
- Repo als **internes IP** lizenziert (siehe `LICENSE`) → auf GitHub **Private** wählen.
- Bild-Harvest nur öffentliche Produktbilder; keine Personen-/LinkedIn-Scraper.
