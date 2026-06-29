# Agent 6 — Phase-2: Konservative ER · Primärquellen · Verifikation Pass 1

Aufbauend auf dem DB-Kern. **Alles hier gegen deinen echten Master validiert.**

## Der entscheidende, ehrliche Befund

Die aggressive Entity-Resolution meldete zuvor „1158 → 673" (485 Merges). Die
**konservative** Version zeigt, was davon belastbar war:

| Kennzahl | Wert |
|---|---|
| Seeds (Master-Zeilen) | 1158 |
| Auto-Merge über **starke Schlüssel** (LEI/VAT/HR) | **0** |
| Auto-Merge über **norm-exakt** | **0** |
| **Review-Kandidaten** (schwacher Match, geloggt) | **230** |
| Distinct (kein Match) | 928 |
| Organisationen gesamt | 1158 |

**Klartext:** Die alten „485 Merges" waren fast vollständig **schwache** Brand-Token-/
Substring-Treffer — riskant. Ohne starke Schlüssel lässt sich **nichts sicher
automatisch deduplizieren**. Die konservative Logik merged deshalb **null**
automatisch, legt alle 1158 als eigenständig an und flaggt **230 Paar-Kandidaten**
zur Mensch-Review (`_merge_review.xlsx`, nach Score sortiert).

**Das ist kein Rückschritt, sondern die Wahrheit:** Präzision vor Recall — lieber ein
Duplikat behalten als einen echten OEM still verlieren.

## Warum die Konnektoren jetzt der Hebel sind

Sichere Deduplizierung braucht **starke Schlüssel**. Genau die liefern die neuen
Primärquellen-Konnektoren:
- **GLEIF** → LEI (globaler, eindeutiger Rechtsträger-Schlüssel), gratis, kein Key.
- **VIES** → VAT-Validierung + offizieller Name/Adresse, gratis, kein Key.
- **Companies House** → UK-Registernummer + Status, gratis (freier Key).
- **Wikidata (SPARQL)** → Website/Land/Branche, gratis, kein Key.

Sobald diese laufen, bekommen die 230 Kandidaten (und alle 1158 Orgs) LEI/VAT —
und **dann** merged die ER sicher über starke Schlüssel statt über Namensähnlichkeit.
Reihenfolge also: erst Schlüssel holen, dann sicher mergen, Rest per Review.

## Verifikations-Loop Pass 1 (validiert)

`verify.py` sammelt Claims mehrerer Konnektoren, schreibt sie mit Provenienz und
vergibt Confidence **nur bei Mehrfachbestätigung** unabhängiger Primärquellen:
- ≥2 Primärquellen einig → `verifiziert` (Confidence bis 1.0)
- 1 Quelle → `einzelquelle` (0.5)
- 0 → `unbestätigt` (0.2)

Validierter Testlauf: GLEIF + VIES bestätigen denselben Rechtsnamen → `verifiziert`,
Confidence 1.0, 4 Claims geschrieben.

## Was du jetzt in der Hand hast (Deliverables)

- `_merge_review.xlsx` — **230 Kandidatenpaare zum Durchgehen** (echtes Arbeitsprodukt).
- `_export.xlsx` — Master-Sicht aus der DB (1158 Orgs, mit Claim-Quellen).
- Konnektoren GLEIF/VIES/Companies House/Wikidata (Parser offline getestet; Live auf deiner Maschine).
- Verifikations-Loop Pass 1.

## Nächste Bausteine

1. **Konnektoren live schalten** (auf deiner Maschine, kein/geringes Budget) → LEI/VAT für alle Orgs holen.
2. **ER erneut laufen** — jetzt mit starken Schlüsseln → sichere Merges; Review-Liste schrumpft drastisch.
3. Impressum-Konnektor (DE: GF + VAT + Adresse aus der Pflichtseite).
4. VLM-Scope-Gate Pass 2 (braucht Anthropic-Key) — Bild+Text-Fusion.
