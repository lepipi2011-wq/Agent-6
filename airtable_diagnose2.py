"""Prueft ALLE vom System befuellten Spalten der Tabelle Review — einzeln.
Zeigt genau, welche fehlt oder den falschen Typ hat, bevor der grosse Lauf startet.
Aufruf:  python airtable_diagnose2.py
"""
import os, requests
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception:
    pass

TOKEN = os.environ.get("AIRTABLE_TOKEN", "")
BASE, TABLE = "app86LDE37W8Mb8Rf", "Review"
hdr = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

print("Token:", bool(TOKEN), "| Länge:", len(TOKEN), "| beginnt mit 'pat':", TOKEN.startswith("pat"))

# Einen Record holen (zum gefahrlosen Testen). Falls Tabelle leer -> Test-Record anlegen.
r = requests.get(f"https://api.airtable.com/v0/{BASE}/{TABLE}",
                 headers=hdr, params={"pageSize": 1}, timeout=30)
recs = r.json().get("records", [])
temp_created = None
if not recs:
    print("Tabelle leer -> lege temporären Test-Record an.")
    rr = requests.post(f"https://api.airtable.com/v0/{BASE}/{TABLE}", headers=hdr,
                       json={"records": [{"fields": {"Bild-ID": "DIAG_TEMP"}}], "typecast": True},
                       timeout=30)
    try:
        temp_created = rr.json()["records"][0]["id"]; rid = temp_created
    except Exception:
        print("Konnte keinen Test-Record anlegen:", rr.text[:200]); raise SystemExit
else:
    rid = recs[0]["id"]
print("Test-Record:", rid, "\n")

# Alle Spalten, die Harvester + Anreicherung + Dedup schreiben — mit realistischen Testwerten
FELDER = [
    ("Bild-URL", "https://example.com/x.jpg"),
    ("Pattern-Vorschlag", "P1 Walk-Behind Deichsel"),
    ("Quelle", "example.com"),
    ("Quell-Seite", "https://example.com/produkt"),
    ("Status", "Neu"),
    ("Harvest-Datum", "2026-07-02"),
    ("OEM", "TEST"),
    ("Modell", "TEST"),
    ("Anwendungsart", "TEST"),
    ("HMI-Typ", "unklar"),
    ("CAN-Bus", "unklar"),
    ("Preis EUR", 12345),
    ("Priorität", "B"),
    ("Dedup-Status", "neu"),
    ("Pipedrive-Firma", "TEST"),
    ("Claude-Urteil", "In-Scope"),
    ("Claude-Konfidenz", 0.87),
    ("Claude-Begründung", "TEST Begründung"),
]

print("=== Einzeltest je Spalte ===")
ok, fehler = [], []
for name, val in FELDER:
    resp = requests.patch(f"https://api.airtable.com/v0/{BASE}/{TABLE}", headers=hdr,
                          json={"records": [{"id": rid, "fields": {name: val}}], "typecast": True},
                          timeout=30)
    if resp.status_code == 200:
        print(f"  ✓ {name}"); ok.append(name)
    else:
        try:
            msg = resp.json().get("error", {}).get("message", resp.text[:120])
        except Exception:
            msg = resp.text[:120]
        print(f"  ✗ {name}  ->  {msg}"); fehler.append((name, msg))

# Testwerte wieder leeren (bzw. Test-Record löschen)
if temp_created:
    requests.delete(f"https://api.airtable.com/v0/{BASE}/{TABLE}/{temp_created}", headers=hdr, timeout=30)
    print("\nTemporären Test-Record wieder gelöscht.")
elif ok:
    requests.patch(f"https://api.airtable.com/v0/{BASE}/{TABLE}", headers=hdr,
                   json={"records": [{"id": rid, "fields": {n: None for n in ok}}], "typecast": True},
                   timeout=30)
    print("\nTestwerte wieder geleert.")

print(f"\n{'='*40}")
print(f"ERGEBNIS: {len(ok)}/{len(FELDER)} Spalten OK.")
if fehler:
    print("FEHLENDE / FALSCHE SPALTEN — bitte in Review anlegen/korrigieren:")
    for name, msg in fehler:
        typ = {"Preis EUR": "Number", "Claude-Konfidenz": "Number",
               "Harvest-Datum": "Date"}.get(name, "Single line text / Single select")
        print(f"  - {name}   (Typ: {typ})   [{msg[:60]}]")
else:
    print("✓✓ Alles bereit — der grosse Lauf kann starten.")
