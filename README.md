# Agent 6 — Engine

Verifikations-first OEM-Discovery & -Verifikation für kettengetriebene Maschinen
(Safety-Remote-Control-Kandidaten). Interne Software der NBB Controls.

**Leitidee:** Die Datenbank ist die Wahrheitsquelle, der Master eine generierte
Export-Sicht. Jede Aussage ist ein *Claim* mit Quelle, Confidence und Zeit.
Qualität vor Quantität — verifiziert wird nur, was mehrere unabhängige
Primärquellen bestätigen.

---

## Schnellstart

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .                                       # Paket + Abhängigkeiten
cp config.example.yaml config.yaml                     # lokale Konfig (gitignored)
# in config.yaml: master.path und database.url setzen
```

Pipeline (Installations-/Betriebs-Abfolge):

```bash
python -m agent6_engine.pipeline init      # DB-Schema
python -m agent6_engine.pipeline import    # Master -> DB (1158 Orgs, 230 Review, Claims)
python -m agent6_engine.pipeline enrich    # Primärquellen -> LEI/VAT + sicheres Re-Merge
python -m agent6_engine.pipeline export     # Master-Sicht + Merge-Review
python -m agent6_engine.pipeline status     # Kennzahlen
```

Bild-Harvest (separat):

```bash
python -m agent6_engine.cli --config config.yaml --live --max-oems 25
# klassenreine Bilder: in config.yaml harvest.vlm_filter=true + ANTHROPIC_API_KEY setzen
```

Details in **[docs/INSTALL_ANLEITUNG.md](docs/INSTALL_ANLEITUNG.md)**.

---

## Projektstruktur

```
agent6-engine/
├── agent6_engine/            # Python-Paket (die Engine)
│   ├── db.py                 # Entity-Graph + Claims (SQLAlchemy)
│   ├── db_import.py          # Master -> DB
│   ├── db_export.py          # DB -> Master-Sicht + Merge-Review
│   ├── entity_resolution.py  # konservative ER + sicheres Re-Merge
│   ├── enrich_keys.py        # Konnektoren über alle Orgs + Re-Resolve
│   ├── verify.py             # Verifikations-Loop Pass 1 (Multi-Quellen)
│   ├── pipeline.py           # CLI: init/import/enrich/export/status
│   ├── connectors/           # GLEIF, VIES, Companies House, Wikidata
│   ├── image_harvest.py      # OEM-direkter Bild-Harvester
│   ├── vlm_filter.py         # VLM-Scope-Gate (Bild gegen Klasse)
│   ├── master_io.py          # header-basiertes Master-Lesen + normalize_class
│   ├── quality_gate.py       # Batch-Metriken (Yield/OEM-direkt/Score)
│   └── cli.py                # Harvester-CLI
├── docs/                     # Anleitung + Phasen-Dokumentation
├── tests/                    # Offline-Smoke-Tests (pytest)
├── config.example.yaml       # Vorlage -> nach config.yaml kopieren
└── pyproject.toml
```

## Architektur (Kurzfassung)

Quell-Konnektoren → Ingestion + Entity-Resolution → Kern (Postgres: Entitäten +
Claims + Klassifikation) → Delivery (Master-Export, Pipedrive, Dashboards),
darunter Orchestrierung & Ops. Zwei Kreisläufe: Verifikation (Qualität) und
Application-Discovery (neue Felder). Ausführlich in `docs/`.

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

## Stand

Gebaut & validiert: DB-Kern, Import/Export, konservative ER, Konnektoren
(GLEIF/VIES/Companies House/Wikidata), Verifikation Pass 1, Bild-Harvester
inkl. Klassen-Normalisierung und VLM-Filter, Pipeline-CLI.
Geplant: Review-Rückspielung, VLM-Scope-Gate als Pipeline-Schritt,
Discovery- & US-Konnektoren, Prefect-Orchestrierung.
