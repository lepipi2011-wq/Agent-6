# Agent 6 — Installations- & Betriebsanleitung

**Stand:** 29.06.2026 · Für das `agent6_engine`-Paket (Phase 1 + 2). Jeder Schritt unten wurde gegen deinen echten Master validiert; die genannten Zahlen sind die erwarteten Checkpoints.

---

## Teil A · Gesamtkontext (Mentales Modell)

Bevor du installierst — so hängt alles zusammen:

**Die Datenbank ist die Wahrheit, der Master ist eine Sicht.** Bisher war die xlsx die Betriebs-DB (langsam, dubletten-anfällig). Ab jetzt: Eine echte Datenbank (SQLite zum Start, Postgres in Prod) hält die **kanonischen Organisationen** und für jede Aussage einen **Claim** (Wert + Quelle + Confidence + Zeit). Der Master wird jederzeit **aus der DB neu exportiert**.

**Der Datenfluss in vier Bewegungen:**
1. **Import** — der Master wird in die DB geladen; die Entity-Resolution legt kanonische Organisationen an und flaggt unsichere Dubletten zur Review (statt sie blind zu mergen).
2. **Enrich** — Primärquellen-Konnektoren (GLEIF, Companies House, Wikidata) holen **starke Schlüssel** (LEI, Registernummer) und Attribute; jede Aussage wird ein Claim.
3. **Re-Resolve** — mit den starken Schlüsseln wird **sicher** gemerged (gleiche LEI = dieselbe Firma). Die Review-Liste schrumpft auf die echten Zweifelsfälle.
4. **Export/Review** — Master-Sicht + Merge-Review als xlsx; ein Mensch entscheidet die Restfälle.

**Warum diese Reihenfolge zwingend ist (der Kernpunkt):** Ohne starke Schlüssel lässt sich **nichts sicher automatisch deduplizieren** — Namensähnlichkeit merged falsch und verliert echte OEMs still. Deshalb: erst Schlüssel holen, **dann** mergen. Genau das hat der Testlauf gezeigt (die alten „485 Merges" waren riskante Namenstreffer; sicher waren 0).

**Was Geld/Keys kostet — und was nicht:** Der gesamte Ablauf bis zur belastbaren Entity-Basis läuft mit **Gratis-/Primärquellen ohne Budget**. Keys für Suche/VLM/DACH-Register kommen erst in späteren Phasen.

---

## Teil B · Voraussetzungen

- **Python 3.11+**
- **Datenbank:** SQLite (nichts zu installieren, ideal zum Start) — oder **Postgres 14+** für Prod.
- Der **Master** `agent6_master_live.xlsx`.
- **API-Keys — nach Bedarf, gestaffelt:**

| Konnektor / Stufe | Key nötig? | Kosten | Ab welcher Phase |
|---|---|---|---|
| GLEIF (LEI) | nein | gratis | jetzt (enrich) |
| VIES (VAT-Validierung) | nein | gratis | jetzt (wenn VAT bekannt) |
| Wikidata (SPARQL) | nein | gratis | jetzt (enrich) |
| Companies House (UK) | **ja** (freier Key) | gratis | jetzt (enrich, UK) |
| Web-Suche (Tavily/SerpApi) | ja | € | Discovery |
| VLM Scope-Gate (Anthropic) | ja | € | Bild-Klassifikation |
| Northdata/Apify (DACH-Register) | ja | € | tiefe DACH-Verifikation |

Für die Schritte 0–6 unten brauchst du **höchstens** einen kostenlosen Companies-House-Key.

---

## Teil C · Installations-Abfolge (Schritt für Schritt)

### Schritt 0 — Code & Umgebung
```bash
unzip agent6_engine_phase2_v2026-06-29.zip && cd agent6_engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Schritt 1 — Konfiguration
`config.yaml` öffnen und zwei Werte setzen:
```yaml
master:
  path: "/pfad/zu/agent6_master_live.xlsx"
database:
  url: "sqlite:///agent6.db"        # Start. Prod: postgresql+psycopg://user:pass@host/agent6
```

### Schritt 2 — DB anlegen & Master importieren
```bash
python -m agent6_engine.pipeline init
python -m agent6_engine.pipeline import
python -m agent6_engine.pipeline status
```
**✅ Checkpoint:** `import` meldet `seeds: 1158, review_candidates: 230, distinct_new: 928, claims: 1388`. `status` zeigt `Organisationen: 1158 | mit LEI: 0 | Review offen: 230`.

### Schritt 3 — (optional) Companies-House-Key
Kostenlos registrieren unter developer.company-information.service.gov.uk, dann:
```bash
export COMPANIES_HOUSE_KEY="dein_free_key"
```
GLEIF, VIES und Wikidata brauchen **keinen** Key.

### Schritt 4 — Schlüssel holen (enrich) + sicheres Re-Merge
Erst an einer Stichprobe testen, dann voll:
```bash
python -m agent6_engine.pipeline enrich --limit 25     # Testlauf
python -m agent6_engine.pipeline enrich                # voll (läuft je nach Anzahl einige Minuten)
```
Dieser Befehl ruft die Konnektoren über jede Organisation auf, schreibt LEI/Adresse/Website als Claims **und** merged anschließend automatisch alle Orgs mit identischem starken Schlüssel.
**✅ Checkpoint:** Ausgabe `ENRICH+RERESOLVE: {orgs_before: 1158, orgs_after: <weniger>, merged_by_strong_key: <n>, lei_found: <n> ...}`. `status` zeigt jetzt `mit LEI: >0` und `Review offen: <deutlich weniger als 230>`.

> `--dry` läuft ohne externe Aufrufe (nur Re-Resolve) — nützlich zum Prüfen der Verdrahtung.

### Schritt 5 — Export & Mensch-Review
```bash
python -m agent6_engine.pipeline export
```
Erzeugt `agent6_export.xlsx` (Master-Sicht aus der DB) und `agent6_merge_review.xlsx` (verbliebene Zweifelsfälle, nach Score sortiert). **Die Review-Datei durchgehen** und die Spalte „Entscheidung" auf `merge`/`keep-separate` setzen. (Das Zurückspielen der Entscheidungen ist der nächste Baustein — siehe Teil F.)

### Schritt 6 — Verifikation Pass 1 (optional jetzt)
Für gezielte Organisationen die Mehrfachbestätigung fahren (≥2 Primärquellen → `verifiziert`). Läuft programmatisch über `agent6_engine.verify.verify_org`; als eigener Pipeline-Schritt kommt er im nächsten Baustein.

---

## Teil D · SQLite → Postgres (für Prod)
1. Postgres bereitstellen (lokal, Docker oder gehostet, EU-Region).
2. In `config.yaml` nur die URL tauschen:
   `database.url: "postgresql+psycopg://user:pass@host:5432/agent6"`
3. `pip install psycopg[binary]`
4. `python -m agent6_engine.pipeline init` erneut (legt Schema in Postgres an), dann `import` etc.
Dieselben Befehle, dieselbe Definition — nur der Speicher wechselt.

---

## Teil E · Betrieb (volles Engineering)
- **Planung:** Die Schritte 4–5 als Prefect-/Dagster-Flow auf einem persistenten Worker (EU-VPS) wöchentlich; Run-Logs = Audit-Trail.
- **Monitoring:** `status` als Health-Check; Kennzahlen (Orgs, mit-LEI-Anteil, offene Reviews) auf ein Dashboard.
- **Cache:** Enrich schreibt Claims mit Zeitstempel — Konnektoren nur erneut anstoßen, wenn Claim älter als Intervall (verhindert doppelte Kosten).
- **CI:** GitHub Actions für Tests/Lint des Pakets.

---

## Teil F · Troubleshooting & nächste Bausteine
- **`import` meldet andere Zahlen als 1158/230:** du nutzt vermutlich die reconciled-Master-Version (mehr Pattern-Coverage) — das ist korrekt, die Zahlen verschieben sich entsprechend.
- **`enrich` findet wenige LEIs:** viele kleine/japanische OEMs haben keinen LEI; das ist erwartbar. Companies House deckt UK, Wikidata deckt bekanntere Firmen. DACH-Tiefe kommt über Northdata (späte Phase, Budget).
- **Review-Liste bleibt groß:** ohne starke Schlüssel bleibt der Fall echt unsicher → Mensch entscheidet. Das ist gewollt (Präzision vor Recall).

**Nächste Bausteine (Reihenfolge):**
1. **Review-Rückspielung** — Entscheidungen aus `agent6_merge_review.xlsx` zurück in die DB (`merge`/`keep-separate` ausführen).
2. **Impressum-Konnektor** (DE: GF + VAT + Adresse aus der Pflichtseite) → mehr starke Schlüssel für DACH.
3. **VLM-Scope-Gate Pass 2** (Anthropic-Key) — Bild+Text-Fusion.
4. **Discovery-Konnektoren** (Marktplätze/Verzeichnisse/Patente) → neue OEMs & Anwendungsfelder.
