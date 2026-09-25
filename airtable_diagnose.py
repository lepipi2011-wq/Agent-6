"""Schreibt EINEN Testdatensatz nach Airtable und zeigt den vollen Fehlertext.
Aufruf:  python airtable_diagnose.py
"""
import os, requests
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception:
    pass

TOKEN = os.environ.get("AIRTABLE_TOKEN", "")
BASE = "app86LDE37W8Mb8Rf"
TABLE = "Review"
print("Token vorhanden:", bool(TOKEN), "| Länge:", len(TOKEN), "| beginnt mit 'pat':", TOKEN.startswith("pat"))

hdr = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# 1) Welche Felder hat die Tabelle wirklich? (Meta-API)
print("\n=== Vorhandene Spalten laut Airtable ===")
try:
    r = requests.get(f"https://api.airtable.com/v0/meta/bases/{BASE}/tables", headers=hdr, timeout=30)
    r.raise_for_status()
    for t in r.json().get("tables", []):
        if t["name"] == TABLE:
            for f in t["fields"]:
                print(f"  {f['name']}  ({f['type']})")
except Exception as e:
    print("  Meta-Abruf fehlgeschlagen:", e, getattr(getattr(e,'response',None),'text','')[:300])

# 2) Testschreibvorgang mit allen Feldern, die der Harvester nutzt
print("\n=== Test-Schreibvorgang ===")
felder = {
    "Bild-ID": "DIAGNOSE_TEST", "Bild-URL": "https://example.com/test.jpg",
    "Pattern-Vorschlag": "P1 Walk-Behind Deichsel", "Query": "test", "Quelle": "test",
    "Status": "Neu", "Harvest-Datum": "2026-07-02", "Quell-Seite": "https://example.com",
}
try:
    r = requests.post(f"https://api.airtable.com/v0/{BASE}/{TABLE}", headers=hdr,
                      json={"records": [{"fields": felder}], "typecast": True}, timeout=30)
    if r.status_code == 200:
        print("  ✓ Schreiben OK — Token und Felder stimmen. Test-Record angelegt (darfst du löschen).")
    else:
        print(f"  ✗ Fehler {r.status_code}:")
        print("  ", r.text[:500])
except Exception as e:
    print("  Ausnahme:", e)
