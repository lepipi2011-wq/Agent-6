# Agent 6 — Phase-1-Kern (DB · Entity-Resolution · Import/Export · Konnektor)

Dies ist das **Skalierungs-Fundament** der Zielarchitektur: der Master wird in einen
kanonischen Entity-Graphen mit Provenienz überführt; die DB ist die Wahrheitsquelle,
der Master wird zur generierten Export-Sicht. **Hier gegen deinen echten Master validiert.**

## Was gebaut & validiert ist

| Modul | Zweck | Validierung |
|---|---|---|
| `db.py` | Entity-Graph + Claims (SQLite/Postgres) | ✅ Schema erzeugt |
| `db_import.py` | Master → DB (Orgs via ER, Patterns, Claims) | ✅ 1158 Seeds importiert |
| `entity_resolution.py` | starke Schlüssel (LEI/VAT/HR) + 3-Stufen-Kaskade | ✅ Varianten gematcht |
| `db_export.py` | DB → Master-Sicht (Hauptsheet-Format) | ✅ Export erzeugt |
| `connectors/gleif.py` | GLEIF/LEI (gratis, kein Key) — Konnektor-Template | ✅ Parser offline getestet |

## Echtdaten-Befund (wichtig)

Beim Import kollabierten **1158 Master-Zeilen auf 673 kanonische Organisationen** —
die Entity-Resolution hat **485 Varianten/Dubletten** zusammengeführt. Das ist der
konkrete Wert der ER-Schicht auf euren Daten.

> **Methodische Warnung (nicht blind übernehmen):** 485 Merges sind eine *Hypothese*,
> kein gesichertes Ergebnis. Die Kaskade nutzt Substring- und Brand-Token-Matching und
> kann bei geteilten Marken-Tokens **fälschlich mergen**. Vor produktivem Einsatz gehört
> ein **Merge-Log mit Mensch-Review** dazu (nächster Baustein). Bis dahin: Zahl als
> Größenordnung lesen, nicht als Fakt.

## Bedienung

```bash
pip install -r requirements.txt

python - <<'PY'
from agent6_engine.config import load_config
from agent6_engine import db, db_import, db_export
cfg = load_config('config.yaml'); cfg['master']['path'] = 'agent6_master_live.xlsx'
eng = db.make_engine('sqlite:///agent6.db')     # Prod: postgresql+psycopg://...
Session = db.init_db(eng); s = Session()
print(db_import.import_master(s, cfg))
db_export.export_master(s, 'agent6_export.xlsx')
PY
```

Postgres statt SQLite: nur die `make_engine`-URL tauschen — dieselbe Definition.

## Konnektoren

`connectors/gleif.py` ist das **Template**: `parse()` ist netzwerkfrei (offline testbar),
`fetch()` macht den Live-Call. Nach demselben Muster folgen VIES, Companies House,
Wikidata (SPARQL), Impressum — die gratis/primär sind und **kein Budget** brauchen.
Der GLEIF-Live-Call läuft auf deiner Maschine (in dieser Sandbox ist externer
Netzzugriff gesperrt, daher offline gegen eine gemockte Antwort getestet).

## Nächste Bausteine (in Reihenfolge)

1. **Merge-Log + Review** für die ER (die 485 Merges auditierbar machen).
2. Weitere Gratis-Konnektoren (VIES, Companies House, Wikidata, Impressum) nach dem GLEIF-Template.
3. Verifikations-Loop Pass 1 (Multi-Quellen-Abgleich) auf DB-Claims.
4. VLM-Scope-Gate Pass 2 (braucht Anthropic-Key).
