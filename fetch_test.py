"""Testet auf DEINEM Rechner, ob der Seitentext ankommt. Aufruf: python fetch_test.py"""
import requests, re

URLS = ["https://www.seppi.com", "https://hopetechnik.com", "https://en.energreen.it",
        "https://www.alibaba.com", "https://www.facebook.com"]

def strip(html):
    html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).strip()

UA_SIMPLE = {"User-Agent": "Mozilla/5.0"}
UA_BROWSER = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
              "Accept-Language": "de,en;q=0.9"}

for url in URLS:
    print(f"\n=== {url} ===")
    for label, ua in [("einfacher UA", UA_SIMPLE), ("Browser-UA", UA_BROWSER)]:
        try:
            r = requests.get(url, headers=ua, timeout=15)
            txt = strip(r.text) if "html" in r.headers.get("content-type","").lower() else ""
            print(f"  {label:14} Status {r.status_code} | HTML {len(r.text):7} Zeichen | Text {len(txt):6} Zeichen")
        except Exception as e:
            print(f"  {label:14} FEHLER: {type(e).__name__}: {e}")
