# Konnektoren

Alle Konnektoren erben von `connectors.base.Connector` und liefern eine Liste von
`ClaimDict(predicate, value, source_url, source_type, confidence)`. `parse()` ist
netzwerkfrei (offline testbar); `fetch()` macht den Live-Call. So bleibt der
Verifikations-Loop quell-agnostisch.

## EU / DACH (`EU_CONNECTORS`)

| Name | Liefert | Key | Prim. |
|---|---|---|---|
| `gleif` | LEI, Rechtsname, Adresse, Status | nein | ✅ |
| `companies_house` | UK-Registernummer, Status, Name | ja (frei, `COMPANIES_HOUSE_KEY`) | ✅ |
| `wikidata` | Website, Land, Branche (SPARQL) | nein | — |
| `impressum` | USt-IdNr, Geschäftsführer (DACH-Pflichtseite) | nein | ✅ |

## US (`US_CONNECTORS`)

| Name | Liefert | Key | Prim. |
|---|---|---|---|
| `gleif` | LEI (auch US) | nein | ✅ |
| `sec_edgar` | CIK, Rechtsname (nur börsennotiert) | nein (User-Agent nötig) | ✅ |
| `sam_gov` | UEI (ersetzt DUNS), Name, Adresse | ja (frei, `SAM_GOV_KEY`) | ✅ |
| `patentsview` | Patentanzahl/-titel (Tech-Signal) | ja (`PATENTSVIEW_KEY`) | — |
| `fcc_id` | Funk-Zulassung → belegt „Funk vorhanden“ | nein (Endpoint konfigurierbar) | ✅ |

## Validatoren (`VALIDATORS`)

| Name | Zweck | Key |
|---|---|---|
| `vies` | EU-VAT prüfen (VAT rein → gültig/Name raus) — **kein Discovery** | nein |

## Nutzung

```python
from agent6_engine import enrich_keys
# EU:  Schlüssel holen + sicheres Re-Merge
enrich_keys.run(session, region="eu")
# US:  gleiche Pipeline, US-Quellen
enrich_keys.run(session, region="us")
```

Oder per CLI: `python -m agent6_engine.pipeline enrich --region us`.

## Hinweise
- **VIES entdeckt keine VATs** — es validiert nur bereits bekannte. Deshalb nicht Teil der Discovery.
- **SEC EDGAR** deckt nur börsennotierte US-Firmen; viele Maschinen-OEMs sind privat.
- **`fcc_id`** hat keine einheitliche offizielle JSON-Suche; `endpoint` auf die gewählte Quelle setzen (interner Spiegel o. Ä.). Der Parser ist quellenunabhängig.
- Alle Live-Calls laufen auf deiner Maschine; die `parse()`-Logik ist per pytest offline abgesichert.
