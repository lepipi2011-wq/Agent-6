# Agent 6 — STATUS (Single Source of Truth)

> **Diese Datei ist die eine Wahrheitsquelle über den Repo-Zustand.**
> Jede neue Claude-Session liest ZUERST diese Datei + `CHANGELOG.md`, bevor sie
> irgendetwas ändert. Sie wird bei JEDER inhaltlichen Iteration mit-aktualisiert
> (Regel siehe unten „Nachhalte-Konvention"). Chat-Wechsel oder Kontext-Kompaktierung
> können das Gedächtnis des Modells löschen — diese Datei nicht.

**Stand:** 2026-09-24 · **Version:** pyproject 1.0.0 / package `__version__` 0.1.0 · **Tests:** 93 grün (17 Dateien) · **Python:** ≥3.11

---

## 1. Zweck der Engine

B2B-Lead-Engine für **NBB Controls** (sichere Funkfernsteuerungen / safety radio remote controls).
Sie findet **getrackte / raupenbasierte Maschinen**, deren **OEMs** Kandidaten für NBB-RC sind.
Zielmärkte: **DACH + USA**. Ergebnis-Datenbank: **Airtable Base `app86LDE37W8Mb8Rf`**.

Leitprinzip (global, nicht verhandelbar): **Trust vor Volumen.** Das Modell soll die
hunderttausend Marktplatz-/Commercial-Aggregatoren und Social/Stock-Quellen **ignorieren**
und sich auf **vertrauenswürdige Primärquellen** (OEM / Presse / Register / Wissenschaft)
fokussieren. Niemals Zahlen-Ziele blind erfüllen, wenn die Qualität sinkt.

---

## 2. Pipeline (2 Stufen)

```
HARVEST                         ENRICHMENT                     NACHGELAGERT
image_search_harvester.py   →   hmi_enrichment.py          →   pipedrive_dedup.py
text_harvester.py               (OEM/Modell/HMI/CAN/            preis_recherche.py
(gesteuert über query_repo.py     Preis/Gewicht/Leistung        scope_score.py (Lern-Monitor)
 / Airtable-Tabelle "Queries")    + Claude-Urteil)
```

- **HARVEST** sucht die MASCHINE (objekt-zentriert), nicht die Firma. Filtert Quellen über `source_trust`.
- **ENRICHMENT** extrahiert Felder + fällt ein Claude-Urteil (Ziel / Out-of-Scope / Unsicher) und schreibt nach Airtable.
- Airtable-Tabellen: **Review** `tbl5mXxeEeqk6Dckq` · **Queries** `tbl2ulInpAvca0etY`.

---

## 3. Kern-Invarianten (NICHT brechen)

1. **Trust-Filter ist single source of truth:** `source_trust.py` — `is_low_trust()`, `block_reason()`,
   `source_score()` (1=Aggregator, 2=Presse, 3=OEM/Primärquelle), `OEM_ALLOWLIST`, `PRESS`,
   Blocklisten `SOCIAL_STOCK`, `MARKETPLACE`, `CDN`. Harvester, Resolver und Quality-Gate rufen ALLE hier an.
2. **Größen-Gate:** `GEWICHT_MIN_T = 0.8` t **ODER** `LEISTUNG_MIN_KW = 8` kW. `groesse_status()` → `ok` / `zu klein` / `unklar`.
   `priorisiere()` erzwingt „X" (raus), wenn `nicht ist_ziel` ODER `claude_urteil == "Out-of-Scope"` ODER `groesse == "zu klein"`.
3. **„No CAN" ≠ Out-of-Scope.** Wenn eine Anwendung passt und nur CAN fehlt → Kandidat bleibt (Aktuator-Retrofit). Immer ins **Datenblatt** schauen, nicht nach Stichwort urteilen.
4. **Airtable Preis-EUR ist eine TEXT-Spalte (singleLineText).** Preis IMMER als String schreiben,
   sonst 422 `INVALID_VALUE_FOR_COLUMN`. Gilt in `hmi_enrichment.update_enrichment` und `preis_recherche`.
5. **Fail-Loud bei Airtable-Schreibfehlern:** `_request_with_retry` (retry bei ConnectionError/Timeout/429/5xx, NICHT bei 422),
   `_patch_batches` zählt `write_failures` und beendet mit **EXIT 2**. Keine stillen Fehlschläge mehr.
6. **Airtable nur über interne IDs** (app…/tbl…/fld…/sel…), nie über Anzeigenamen.
7. **Queries-Regel:** Der Haken **„Aktiv"** in der Queries-Tabelle wird **ausschließlich von Pierre** gesetzt.

---

## 4. Modul-Landkarte (`agent6_engine/`)

| Modul | Aufgabe |
|---|---|
| `pipeline.py` | Betriebs-CLI (init/import/enrich/review/export/status/verify/all/discover). Entry-Point `agent6`. |
| `cli.py` | Alternativer Einstiegspunkt `python -m agent6_engine.cli`. |
| `config.py` / `config.yaml` | Konfiguration (YAML) mit robusten Defaults. |
| `db.py` / `db_import.py` / `db_export.py` | Entity-Graph + Claims; Master↔DB (header-basiert, struktur-erhaltend). |
| `master_io.py` | Master-I/O, header-basiert, struktur-erhaltend. |
| `query_repo.py` | Query-Repository — Suchanfragen leben in Airtable („Queries"), nicht im Code. |
| `image_search_harvester.py` | Objekt-zentrierter Bild-Harvester + **AirtableWriter** (Retry/Fail-Loud, `candidates_missing/_reenrich/_all`). |
| `image_harvest.py` | OEM-direkter Bild-Harvester. |
| `text_harvester.py` | Text-Harvester — In-Scope-Kandidaten über die SPRACHE der Datenblätter. |
| `harvest_rules.py` | Bildsuche-Training → maschinell ausführbare Harvest-Regeln. |
| `vlm_filter.py` | VLM-Download-Filter — inhaltlicher Scope-Gate (optional, `harvest.vlm_filter=true`). |
| `hmi_enrichment.py` | **Stufe 2:** HMI-/Anwendungs-Anreicherung. Größen-Gate, `priorisiere()`, `--reenrich-all/-unsicher`. |
| `source_trust.py` | **Quellen-Vertrauen — die eine Wahrheit** für Harvester/Resolver/Quality-Gate. |
| `quality_gate.py` | Quality-Gate für den Harvest-Batch (Yield / A+B / Score). |
| `entity_resolution.py` | Entity-Resolution, konservativ + auditierbar. |
| `enrich_keys.py` | Starke Schlüssel/Attribute je Organisation. |
| `discovery.py` | Neue OEM-Kandidaten für bestehende Patterns finden. |
| `verify.py` | Verifikations-Loop Pass 1 — Multi-Quellen-Abgleich. |
| `scope_audit.py` | Scope-Audit — pro OEM ein In-Scope-Urteil. |
| `scope_score.py` | Scope-Score — Claude-Urteil gegen Mensch-Verdikte (Lern-Monitor). |
| `pipedrive_dedup.py` | Pipedrive-Dedup über ZWEI Dimensionen: Firma UND Anwendung. |
| `preis_recherche.py` | Preis-Recherche — Größenordnung statt exaktem Preis. |
| `review_apply.py` | Review-Rückspielung aus Merge-Review-xlsx. |
| `connectors/` | Register-/Primärquellen: `gleif`, `companies_house`, `sec_edgar`, `sam_gov`, `fcc_id`, `patentsview`, `vies`, `wikidata`, `impressum` (+ `base`). |

---

## 5. Betrieb (die wichtigsten Läufe)

> **Immer aus der Wurzel `agent6-engine\` starten.** `ANTHROPIC_API_KEY` muss gesetzt sein.

```bash
# Tests
python -m pytest -q

# Re-Enrichment ALLER Airtable-Records (füllt OEM/Preis/Größe nach)
python -m agent6_engine.hmi_enrichment --from-airtable --reenrich-all --airtable

# Nur die "Unsicher"-Records nachbearbeiten
python -m agent6_engine.hmi_enrichment --from-airtable --reenrich-unsicher --airtable

# Preis-Recherche (schreibt Preis-Indikation als STRING zurück)
python -m agent6_engine.preis_recherche --airtable

# Voll-Betrieb / Discovery neuer Prospects
python -m agent6_engine.pipeline discover --patterns P4,P5 --per-pattern 8
python -m agent6_engine.pipeline all
```

---

## 6. Bekannte Fallen (schon gelöst — nicht neu einführen)

- **422 auf Preis-EUR** = numerisch in Text-Spalte → String-Coercion (Invariante 4).
- **`No module named 'dotenv'`** → `pip install python-dotenv`. `requirements.txt` hat Tippfehler `npython-dotenv` (Zeile 1) → separat `pip install anthropic pypdf` bzw. `python-dotenv`.
- **`test_no_key` schlägt fehl, wenn `ANTHROPIC_API_KEY` gesetzt ist** → Test ist mit `monkeypatch.setattr(H,"_client", lambda: None)` deterministisch gemacht.
- **Doppelte `test_hmi_enrichment.py`** (Engine- + tests-Ordner) → Tests NUR unter `tests/` halten.
- **DNS-/Proxy-Fehler** bei Läufen → Netzwerk/VPN prüfen, kein Code-Fehler.

---

## 7. Offene Punkte (TODO — Reihenfolge)

1. **Repo verschlanken.** Müll aus der Windows-Arbeitskopie raus (siehe `.gitignore`): `.venv/`, `out/`, `agent6.db`,
   `probe*/reenrich*/enrich_all*` CSV+JSON, `deals_Pipedrive.xlsx`, `agent6_master_live*.xlsx`, die drei `*.patch`,
   `airtable_diagnose*.py`, `fetch_test*.py`, stray `agent6_master_live.xlsx` **im** `agent6_engine/`.
   Entscheidung offen: Altmodule **löschen vs. nach `legacy/` verschieben** (reversibel).
2. **`--verify-specs` bauen.** Spec-Verifikations-Schritt: sucht aktiv die OEM-Datenblatt-/Spec-Seite eines Records,
   extrahiert CAN / Gewicht / Leistung, schreibt zurück nach Airtable. Generalisiert die manuelle Datenblatt-Prüfung.
3. **Pipedrive-Organisations-Transfer bauen.** `Pipedrive_Transfer == true` → neue Orgs in Pipedrive anlegen,
   inkl. Anwendung / Gewicht / Leistung; Cleanup der „AUSSER SCOPE:"-Präfixe + OEM-Namen vervollständigen.

---

## 8. Pipedrive_Transfer — verifizierter Wissensstand (Datenblätter)

| OEM / Modell | Gewicht | Leistung | Antrieb | CAN | Urteil |
|---|---|---|---|---|---|
| Altoz TRX 766i | ~0,77 t | 28,7 kW | hydrostatisch + mechanisch | NEIN | Ziel (Aktuator-Retrofit) |
| Orec ZHR800 | 0,32 t | ~8,7 kW | hydrostatisch | NEIN | Ziel (grenzwertig Gewicht) |
| Baumalight MS530M | — | — | Anbaugerät | — | KEIN Org-Ziel (Attachment) |
| PeK Slopehelper | — | — | vollautonom | — | RC-Fit fraglich |
| Farmry | — | — | — | — | bereits Funk |

→ Von den 8 Pipedrive_Transfer-Records sind nur ~2 (Altoz, Orec) saubere Tracked-Machine-Ziele.

---

## 9. Nachhalte-Konvention (WIE wir Wissen transparent halten)

- **`STATUS.md`** (diese Datei) = aktueller Zustand + Invarianten + TODO. Wird bei jeder Iteration mit-aktualisiert.
- **`CHANGELOG.md`** = chronologischer Iterations-Log. Jede inhaltliche Änderung bekommt einen Eintrag.
- **Git** = die eigentliche lückenlose Historie. Jede Iteration = 1 Commit; Commit-Message beschreibt das WAS + WARUM.
- **Projekt-Doc `claude/Agent6_Repo-Status.md`** = Spiegel dieser Datei im claude.ai-Projekt „RC Agents",
  damit jede neue Session (auch ohne Repo-Zugriff) den Stand sieht.
- **Regel für jede neue Session:** zuerst `STATUS.md` + `CHANGELOG.md` lesen, dann arbeiten, am Ende beide fortschreiben.
