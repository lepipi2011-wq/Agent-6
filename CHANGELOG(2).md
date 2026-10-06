# Agent 6 — CHANGELOG (Iterations-Log)

> Chronologischer Log aller inhaltlichen Iterationen. Neueste oben.
> Jede Zeile: WAS geändert wurde + WARUM. Ergänzt die lückenlose Git-Historie.

## 2026-09-28 — KORREKTUR: CAN ist Pflicht, SIL schließt aus (Suchbaum-Abgleich)
- Nach Abgleich mit `Search_approach.pdf` (Ziel-Zweig „Ready" = Crawler + CAN) + `Agent6_Vorgehensweise` v1–v3:
  frühere Fehl-Interpretation korrigiert. **CAN = Pflichtkriterium; „No Can" = kein Ziel → Out.**
- `hmi_enrichment.py`: enrich-Prompt (CAN Pflicht + `sil_pflicht`/`sil_beleg` neu), Few-Shot umgedreht (No-CAN → Out,
  SIL → Out), `priorisiere()` erweitert: `_can_absent`→X, `sil_pflicht`→X, „unklar" bleibt C (→ verify-specs); Row+CSV+run() um SIL ergänzt.
- `eval_scope.py`: „No Can" von ZIEL nach KEIN. **Baseline neu:** echte Ziele 99→**36**, Recall **13,9 %** (5/36),
  Precision 13,2 %, FN=31. (Die alte 16-%-Zahl beruhte auf falscher Ziel-Definition.)
- `DOMAIN_RULES`: R3 umgedreht, **R8 (SIL)** + **R9 (Was wir aus dem Review lernen)** neu.
- Tests angepasst/ergänzt (CAN-Pflicht, SIL, No-Can=KEIN) → **106 grün**.

## 2026-09-29 — Run-Differenzierung / Historie
- **`run_tracking.py` neu:** Run-ID (`YYYYMMDD-HHMM-vX.Y`), `REGEL_VERSION` (Prämissen-Stand), Git-Commit,
  Review-Snapshot (Vorher/Nachher) + lokaler Run-Log unter `runs/`. Reiner, testbarer Kern.
- **`AirtableWriter`:** `stamp_run()` stempelt Run-ID/Regel-Version an jeden Review-Record (separat, bricht Kern-Write
  nicht); `log_run()` schreibt eine Zeile in die neue **Runs**-Tabelle. `run()` erzeugt Run-ID, snapshottet den
  Eingangsstand, stempelt + loggt am Ende.
- **Airtable-Schema erweitert:** Tabelle **`Runs`** (tblMUF0YQsb7tfDmh: Run-ID, Datum, Regel-Version, Commit, Query-Set,
  Records, Recall, Precision, Yield, Notiz) + Review-Felder **`Run-ID`**/**`Regel-Version`**.
- Historie dreistufig: Airtable Review = aktueller Stand + Run-Stempel · Runs-Tabelle = Prämissen-Historie · `runs/` im Repo = Snapshots + Run-Logs (Audit-Trail).
- 5 neue Tests → **111 grün**.

## 2026-09-29 — Dedup A + C (Dubletten vermeiden)
- **A — URL-Normalisierung im Harvest-Dedup:** `norm_url()` (ohne Schema/Query/Fragment/www/Trailing-Slash +
  CDN-Größensuffixe) in `existing_urls()` und im Harvest-`seen`. Fängt http/https-, Query- und Größen-Varianten desselben Bildes.
- **C — Entitäts-Dedup:** `norm_oem()` (Rechtsform/Land-Suffixe raus), `dedup_key()` (erster OEM-Token + norm. Modell),
  `mark_duplicates()` → best-gefüllter Record je (OEM,Modell) bleibt, Rest wird als **„Intern-Duplikat = Duplikat"** markiert.
  `run()` schreibt das ins neue Review-Feld **`Intern-Duplikat`** (getrennt von Pipedrive `Dedup-Status`); CSV `final` filtert Duplikate.
- Befund an echten Daten: 24 (OEM,Modell)-Kombis mehrfach (75 Records) + Namensvarianten (colmac/colmac italia, fae/fae group, pek agroline/automotive).
- 6 neue Tests → **116 grün**.
- **Entscheidung:** Pipedrive-Cleanup/-Dedup läuft **immer im Nachgang** (in-session über den Composio-Connector),
  NICHT im lokalen Cron. Der lokale `pipedrive_dedup.py` (xlsx-basiert) bleibt optional, ist aber nicht mehr der Standardweg.

## [Unreleased] — offen
- Urteilsschicht reparieren: OEM-Resolve VOR dem Urteil + Few-Shot aus echten Labels (Ziel: Recall 16 % → >80 %).
- `--verify-specs`: automatische Datenblatt-Verifikation (CAN/Gewicht/Leistung → Airtable), gründlich.
- Repo verschlanken (`.gitignore` greift). Pipedrive-Organisations-Transfer (`Pipedrive_Transfer == true`).

## 2026-09-25 — BEFUND: GitHub-Repo veraltet + Sicherheits-Fix .gitignore
- **`github.com/lepipi2011-wq/Agent-6` ist NICHT der aktuelle Stand.** Beide Branches (main, Production_branch),
  15 Commits gesamt: `source_trust.py` fehlt komplett, nur 2 Testdateien, kein Größen-Gate/Re-Enrichment/Airtable-Retry/
  Preis-EUR-Fix. Der aktuelle Code lebt lokal (D:\…\agent6-engine) + im agent6_src.zip-Snapshot. → GitHub muss vom
  lokalen Repo überschrieben werden (force-push), damit es als Backup/Sync-Punkt taugt.
- **`.gitignore` Sicherheits-Fix:** `config.yaml`, `*.key`, `*.pem` ergänzt (dürfen wegen Keys NIE ins Repo).

## 2026-09-24 — Urteilsschicht kalibriert (Schritt 2)
- **`FEW_SHOT_URTEIL` in `hmi_enrichment.enrich`:** 5 Beispiele aus echten Review-Verdikten kalibrieren die
  Urteilsschicht (No-Can=In-Scope, schon-RC=Out, autonom=Out, Rad/Bauteil=Out, dünne/Aggregator-Quelle=Unsicher).
- **Anti-Über-Ablehnung:** Prompt urteilt nicht mehr vorschnell „Out-of-Scope"; dünne Quelle → „Unsicher" (wird
  nachaufgelöst statt verworfen). Adressiert die 83 False Negatives der Baseline.
- 2 neue Tests → **102 Tests grün**. Wirkung wird per Messlauf gegen die 16-%-Baseline geprüft.

## 2026-09-24 — Eval-Harness (Messbarkeit)
- **`eval_scope.py` neu:** misst die Scope-Urteilsschicht gegen die menschlichen Review-Verdikte (Goldset).
  Reine, testbare Kernfunktionen (`gold_label`/`pred_label`/`score`/`scorecard`) + `main()` (liest Airtable-JSON/CSV).
  ZIEL = Mensch-Verdikt In-Scope ODER No Can; Vorhersage = Claude-Urteil In-Scope. Unsicher/leer werden ignoriert.
- **`test_eval_scope.py` neu** (5 Tests) → **100 Tests grün**.
- **BASELINE gemessen (303 Records, 241 bewertet):** Recall **16,2 %** (16/99 Ziele), Precision 42,1 %, F1 23,4 %,
  FN=83 (echte Ziele verworfen). Das ist die Referenz, gegen die jeder künftige Fix gemessen wird.

## 2026-09-24 — Nachhaltbarkeit & Übergabe nach Chat-Wechsel
- **STATUS.md + CHANGELOG.md eingeführt** als Single Source of Truth über Repo-Zustand und Iterationen,
  gespiegelt ins Projekt-Doc `claude/Agent6_Repo-Status.md`. Grund: Chat-Wechsel/Kontext-Kompaktierung
  darf das Projektwissen nicht mehr verlieren.
- **`BRIEFING_Agent6.md` vollständig in STATUS.md gemerged** — Kontext (Menschen/Ton/Budget, Erstausrüstung-Insight),
  Klassifikation (16 Muster P1–P16, CAN 4-stufig, 5 HMI-Typen, A/B/C/X), Infrastruktur (SerpAPI, Keys, Pipedrive,
  Wochen-Cron), Betriebsregeln (Wurzel `agent6-engine\`, Feldnamen buchstabengenau, diagnose2 18/18, Bündel-Write),
  Architektur-Stufe (Embedding-Suche + eigener Scope-Klassifikator). STATUS.md ist damit die vollständige, gepflegte Fassung.
- **CAN-Regel reconciled:** Briefing-Grundsatz „rein-hydraulisch ohne CAN nicht nachrüstbar" verfeinert um Pierres
  Korrektur — „no can" heißt Anwendung passt, nur CAN fehlt → Aktuator-Retrofit-Kandidat; nie automatisch Out-of-Scope.
- `.gitignore` ergänzt (Müll/Ausgaben/Altdateien aus der Windows-Arbeitskopie).
- Ist-Zustand verifiziert: 93 Tests grün (17 Testdateien), Engine vollständig (34 Module + 10 Connectors).

## 2026-09-24 — Bild-Heuristik Betriebsschnittstelle + CAN-Prompt-Fix (Code)
- **Neue Fachregel R2 (Pierre) verankert:** Fehlen Kabine/Plattform/Sitz/Deichsel → autonom oder bereits ferngesteuert
  → Out-of-Scope; mind. eine Schnittstelle → In-Scope-Signal. CAN/Spez NICHT aus dem Bild (dafür Datenblatt).
  - `hmi_enrichment.operator_interface_scope()` neu (pure, testbar) + 2 Tests → **95 Tests grün**.
  - Bild-Prompt `vlm_filter.keep_image` um Betriebsschnittstelle ergänzt; enrich-Prompt `claude_urteil` um die Bauart-Heuristik.
- **CAN-Widerspruch im enrich-Prompt behoben:** alte Zeile „Ohne CAN/E-Hydraulik NICHT nachrüstbar" (verursachte
  Über-Ablehnung, Befund 1) ersetzt durch Pierres Regel „fehlendes CAN ist kein Ausschluss, Aktuator-Retrofit denkbar".
- **`DOMAIN_RULES.md` neu** — kanonische Scope-Regeln R1–R7, jede mit Code+Test-Verankerung. „Forever"-Prinzip dokumentiert:
  Fachregel = Text + Code + Test.

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
