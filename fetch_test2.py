"""Testet fetch_deep auf den ECHTEN Quell-Seiten aus agent6_enriched.csv —
also exakt den Pfad, den die Anreicherung nimmt. Aufruf: python fetch_test2.py"""
import csv, sys
sys.path.insert(0, ".")
from agent6_engine.hmi_enrichment import fetch_deep, fetch_page_text, _find_datasheet_pdf

rows = list(csv.DictReader(open("agent6_enriched.csv", encoding="utf-8-sig")))
# erste 10 mit nicht-leerer Quell-Seite, die keine Social/Markt-Domain ist
JUNK = ("facebook.", "alibaba.", "tiktok.", "instagram.", "pinterest.", "youtube.")
seen = set()
n = 0
for r in rows:
    url = r.get("quell_seite", "")
    if not url or any(j in url for j in JUNK) or url in seen:
        continue
    seen.add(url)
    n += 1
    if n > 10:
        break
    print(f"\n[{n}] {url[:78]}")
    try:
        raw = fetch_page_text(url)      # nur HTML
        print(f"    fetch_page_text: {len(raw):6} Zeichen")
    except Exception as e:
        print(f"    fetch_page_text FEHLER: {type(e).__name__}: {e}")
    try:
        deep = fetch_deep(url)          # HTML + PDF (was die Anreicherung nutzt)
        print(f"    fetch_deep:      {len(deep):6} Zeichen  | Anfang: {deep[:60]!r}")
    except Exception as e:
        print(f"    fetch_deep FEHLER: {type(e).__name__}: {e}")
