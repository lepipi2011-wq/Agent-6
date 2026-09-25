# Agent 6 — CHANGELOG (Iterations-Log)

> Chronologischer Log aller inhaltlichen Iterationen. Neueste oben.
> Jede Zeile: WAS geändert wurde + WARUM. Ergänzt die lückenlose Git-Historie.

## [Unreleased] — offen
- Repo verschlanken (Müll/Altmodule; `.gitignore` greift). Entscheidung löschen vs. `legacy/` offen.
- `--verify-specs`: automatische Datenblatt-Verifikation (CAN/Gewicht/Leistung → Airtable).
- Pipedrive-Organisations-Transfer (`Pipedrive_Transfer == true` → neue Orgs).

## 2026-09-24 — Nachhaltbarkeit & Übergabe nach Chat-Wechsel
- **STATUS.md + CHANGELOG.md eingeführt** als Single Source of Truth über Repo-Zustand und Iterationen,
  gespiegelt ins Projekt-Doc `claude/Agent6_Repo-Status.md`. Grund: Chat-Wechsel/Kontext-Kompaktierung
  darf das Projektwissen nicht mehr verlieren.
- Ist-Zustand verifiziert: 93 Tests grün (17 Testdateien), Engine vollständig (34 Module + 10 Connectors).

## Frühere Iterationen (verdichtet aus dem vorigen Chat, ~57+ Commits)

### Größen-Gate (Gewicht + Leistung)
- `hmi_enrichment.py`: Konstanten `GEWICHT_MIN_T=0.8`, `LEISTUNG_MIN_KW=8`; `groesse_status()` (ok/zu klein/unklar);
  `priorisiere(..., ist_ziel, claude_urteil, groesse)` erzwingt „X" bei nicht-Ziel / Out-of-Scope / zu klein.
- Prompt erweitert um `gewicht_t` / `leistung_kw` / `groesse_beleg`; Größenfelder in SEPARATEM Airtable-Update
  (`Gewicht-t` / `Leistung-kW` / `Größe-Status`), damit eine fehlende Spalte den Kern-Write nicht bricht.
- Kriterium entspricht der dokumentierten Cluster-6 / v3-Methodik.

### Re-Enrichment
- `--reenrich-all` (alle Records neu) und `--reenrich-unsicher` (nur Urteil „Unsicher") ergänzt.
  Grund: einmal auf „unklar" angereicherte Records wurden nie erneut verarbeitet → OEM/Preis fehlten dauerhaft.
- Record-Auswahlmodi: `candidates_missing` / `candidates_reenrich("Unsicher")` / `candidates_all(limit)`.

### Trust-Filter (Trust vor Volumen)
- **`source_trust.py` neu:** eine Wahrheit für Harvester/Resolver/Quality-Gate. Blocklisten SOCIAL_STOCK / MARKETPLACE / CDN,
  `is_low_trust()`, `block_reason()`, `source_score()` (1/2/3), `OEM_ALLOWLIST`, `PRESS`.
- Harvester `is_junk` delegiert an `source_trust.is_low_trust`; `harvest()` misst blocked-by-category, cheap_share, quellen_score.

### Airtable-Robustheit
- `_request_with_retry` (retry bei ConnectionError/Timeout/429/5xx, NICHT bei 422).
- `_patch_batches` mit `write_failures`-Zähler + Fail-Loud + **EXIT 2**. Grund: Schreibfehler waren vorher still.
- **Preis-EUR als String** (Airtable-Spalte = singleLineText). Fix in `update_enrichment` und `preis_recherche`
  (`"" if preis in (None,"") else str(preis)`). Behebt 422 `INVALID_VALUE_FOR_COLUMN`.

### Datenblatt-Verifikation (manuell, Vorlage für --verify-specs)
- „No CAN"-Records real geprüft (Altoz TRX 766i, Orec ZHR800, Baumalight MS530M, PeK Slopehelper, Farmry) —
  Regel etabliert: „no can" heißt Anwendung passt, nur CAN fehlt → nicht Out-of-Scope. Ergebnisse nach Airtable geschrieben.

### Tests
- Neu: `test_source_trust.py`, `test_airtable_retry.py`; `test_hmi_enrichment.py` erweitert
  (groesse_status / priorisiere / candidates_reenrich / candidates_all; `test_no_key` via monkeypatch deterministisch).
- Stand: 93 Tests grün, 17 Testdateien.

### Vertriebs-Dokumentation
- `Agent6_Vertriebs_Anleitung_v2.docx` (Anhang A quer: Review-Felder-Tabelle + Screenshot; Abschnitt 11 entfernt).
- `Agent6_Query-Repo_Anleitung.docx` (rote Regelbox „Haken ‚Aktiv' nur durch Pierre"; Queries-Screenshot).
- Projekt-Doc `claude/Agent6_Kernprinzip_Quellen-Trust.md`.
