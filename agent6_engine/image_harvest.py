"""OEM-direkter Bild-Harvester.

Reihenfolge je OEM: (1) Produktseite der OEM-Domain crawlen -> volle Auflösung,
klassenrein, Quellen-Score 3. (2) Auffüllen via Bildsuche (SerpAPI), gefiltert
durch die Bildsuche-Training-Regeln, Quellen-Score 1. Danach pHash-Dedup.
Jede Datei wird in sources.csv mit Provenienz protokolliert.

DRY_RUN=true lädt nichts und macht keine API-Calls (deterministischer Mock),
sodass die Verdrahtung offline geprüft werden kann.
"""
from __future__ import annotations
import os, re, csv, io, time, hashlib, datetime
import requests
try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

from .master_io import Seed, Pattern
from .harvest_rules import HarvestRules
from . import vlm_filter

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
_SKIP_IN_URL = ("logo", "icon", "sprite", "favicon", "placeholder", "thumb", "avatar", "flag",
                "banner", "header", "footer", "/nav", "hero", "teaser", "slider", "cookie",
                "social", "/bg", "background", "pixel", "spacer", "loading")


def _safe(s):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(s)).strip("-") or "unknown"


def _looks_like_image(url):
    u = url.lower().split("?")[0]
    if any(bad in u for bad in _SKIP_IN_URL):
        return False
    return u.endswith(IMG_EXT) or "/products" in u or "/produkt" in u or "og:image" in url


# ---------------------------------------------------------------- HTTP helpers
def _get(url, cfg):
    """Robuster GET: probiert www<->non-www, verify=False bei Zertifikatsfehlern,
    und http als letzten Fallback. DNS-Fehler (tote Domain) sind nicht behebbar."""
    ua = {"User-Agent": cfg["harvest"]["user_agent"]}
    to = cfg["harvest"]["request_timeout"]
    variants = [url]
    m = re.match(r"(https?://)(www\.)?(.+)", url)
    if m:
        scheme, www, rest = m.groups()
        variants.append(scheme + ("" if www else "www.") + rest)
    last = None
    for v in variants:
        for verify in (True, False):
            try:
                return requests.get(v, timeout=to, headers=ua, verify=verify)
            except Exception as e:
                last = e
    if url.startswith("https://"):
        try:
            return requests.get("http://" + url[8:], timeout=to, headers=ua)
        except Exception as e:
            last = e
    raise last


def _extract_images(html, base):
    urls = []
    for m in re.finditer(r'property=["\']og:image["\']\s+content=["\']([^"\']+)', html, re.I):
        urls.append(m.group(1))
    for m in re.finditer(r'<img[^>]+(?:data-src|src)=["\']([^"\']+)', html, re.I):
        urls.append(m.group(1))
    out = []
    for u in urls:
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            u = base.rstrip("/") + u
        elif not u.startswith("http"):
            continue
        if _looks_like_image(u) and u not in out:
            out.append(u)
    return out


def _find_product_pages(html, base, limit):
    pages = set()
    for m in re.finditer(r'href=["\']([^"\']+)', html, re.I):
        href = m.group(1)
        if any(k in href.lower() for k in ("product", "produkt", "machine", "maschin",
                                            "range", "model", "serie", "equipment")):
            if href.startswith("/"):
                href = base.rstrip("/") + href
            if href.startswith(base):
                pages.add(href)
        if len(pages) >= limit:
            break
    return list(pages)[:limit]


# --------------------------------------------------------------- harvest paths
def discover_oem_direct(domain, cfg):
    """Liste (img_url, page_url) von der OEM-Domain. DRY_RUN -> Mock."""
    if cfg["harvest"]["dry_run"]:
        n = (abs(hash(domain)) % 6) + 3  # 3..8 Mock-Bilder
        return [(f"{domain}/products/img_{i}.jpg", f"{domain}/products") for i in range(n)]
    found = []
    try:
        home = _get(domain, cfg).text
        pages = [domain] + _find_product_pages(home, domain, cfg["harvest"]["max_pages_per_site"])
        for pg in pages:
            try:
                html = _get(pg, cfg).text
            except Exception:
                continue
            for img in _extract_images(html, domain):
                found.append((img, pg))
            time.sleep(0.3)
    except Exception as e:
        print(f"  OEM-direkt fehlgeschlagen ({domain}): {e}")
    # dedup nach URL
    seen = set(); uniq = []
    for img, pg in found:
        if img not in seen:
            seen.add(img); uniq.append((img, pg))
    return uniq


def search_images(query, cfg):
    """Bildsuche-Fallback. DRY_RUN -> Mock. SerpAPI -> google_images."""
    if cfg["harvest"]["dry_run"]:
        n = (abs(hash(query)) % 4) + 2
        return [f"https://img.example.com/{_safe(query)[:20]}_{i}.jpg" for i in range(n)]
    prov = cfg["search"]["provider"]
    if prov == "serpapi":
        key = os.environ.get(cfg["search"]["serpapi_env"], "")
        if not key:
            return []
        try:
            r = requests.get("https://serpapi.com/search.json",
                             params={"engine": "google_images", "q": query,
                                     "num": cfg["search"]["results_per_query"], "api_key": key},
                             timeout=cfg["harvest"]["request_timeout"])
            return [x.get("original") for x in r.json().get("images_results", [])
                    if x.get("original")][: cfg["search"]["results_per_query"]]
        except Exception as e:
            print(f"  SerpAPI-Fehler: {e}")
            return []
    return []


def download(url, dest, cfg):
    """Lädt ein Bild. DRY_RUN -> 0-Byte-Platzhalter. Live -> Größen-/Lesbarkeitsfilter
    (verwirft Logos/Icons/Banner-Streifen und kaputte Dateien)."""
    if cfg["harvest"]["dry_run"]:
        open(dest, "wb").close()
        return True
    try:
        r = _get(url, cfg)
        if r.status_code == 200 and r.content and len(r.content) > 3072:
            minpx = cfg["harvest"].get("min_image_px", 300)
            if minpx:
                try:
                    from PIL import Image
                    im = Image.open(io.BytesIO(r.content))
                    w, h = im.size
                    if min(w, h) < minpx:                      # zu klein -> Logo/Icon
                        return False
                    if max(w, h) / max(1, min(w, h)) > 4:      # Banner-Streifen
                        return False
                except Exception:
                    return False                                # nicht lesbar
            with open(dest, "wb") as f:
                f.write(r.content)
            return True
    except Exception:
        pass
    return False


# ------------------------------------------------------------------- provenance
def _log_source(sources_path, row):
    new = not os.path.exists(sources_path)
    with open(sources_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["filepath", "class", "oem", "pattern", "source_url",
                        "source_type", "source_score", "license", "harvested_at"])
        w.writerow(row)


# ------------------------------------------------------------------- per OEM
def harvest_oem(seed: Seed, cls: str, cfg, rules: HarvestRules, patterns, stats):
    cls_safe = _safe(cls)                 # Klasse enthält evtl. '/' oder '—' -> pfadsicher machen
    out_dir = os.path.join(cfg["output"]["dir"], "raw", cls_safe)
    os.makedirs(out_dir, exist_ok=True)
    sources_path = os.path.join(cfg["output"]["dir"], cfg["output"]["sources_csv"])
    target = cfg["harvest"]["images_per_oem"]
    ss = cfg["source_score"]
    oem_safe = _safe(seed.oem)
    got = 0

    candidates = []  # (img_url, page_url, source_type, score)
    if cfg["harvest"]["oem_direct_first"] and seed.domain:
        for img, pg in discover_oem_direct(seed.domain, cfg):
            candidates.append((img, pg, "oem_direct", ss["oem_direct"]))

    # Bildsuche auffüllen — sofern Pattern nicht 'text-only'
    pat = seed.pattern
    if got + len(candidates) < target and not (pat and rules.is_text_only(pat)):
        base_q = patterns.get(pat).img_query if (pat and pat in patterns) else None
        query = rules.query_for(pat or "", seed.oem, base_q)
        for img in search_images(query, cfg):
            candidates.append((img, query, "image_search", ss["image_search"]))

    for idx, (img_url, src_url, stype, score) in enumerate(candidates):
        if got >= target:
            break
        fname = cfg["output"]["filename_pattern"].format(cls=cls_safe, oem=oem_safe, idx=idx)
        dest = os.path.join(out_dir, fname)
        if download(img_url, dest, cfg):
            keep, why = vlm_filter.keep_image(dest, cls, patterns, cfg)
            if not keep:
                try: os.remove(dest)
                except OSError: pass
                stats["rejected"] += 1
                stats["dropped_filter"] += 1
                continue
            _log_source(sources_path, [dest, cls_safe, seed.oem, pat or "", img_url, stype,
                                       score, "public-web", datetime.datetime.now().isoformat(timespec="seconds")])
            stats["kept"] += 1
            stats["scores"].append(score)
            if stype == "oem_direct":
                stats["oem_direct"] += 1
            got += 1
        else:
            stats["rejected"] += 1
            stats["dropped_filter"] += 1
    if got == 0:
        stats["oem_empty"] += 1
    return got


# --------------------------------------------------------------- pHash dedup
def phash_dedup(folder, threshold, stats):
    try:
        import imagehash
        from PIL import Image
    except Exception:
        print("  (imagehash/Pillow fehlt -> Dedup übersprungen)")
        return
    seen = []
    for root, _, files in os.walk(folder):
        for fn in sorted(files):
            if not fn.lower().endswith(IMG_EXT):
                continue
            p = os.path.join(root, fn)
            try:
                if os.path.getsize(p) == 0:  # DRY_RUN-Platzhalter
                    continue
                h = imagehash.phash(Image.open(p).convert("RGB"))
            except Exception:
                continue
            if any((h - hh) <= threshold for hh in seen):
                os.remove(p)
                stats["dropped_dedup"] += 1
                stats["kept"] = max(0, stats["kept"] - 1)
                stats["rejected"] += 1
            else:
                seen.append(h)


# ------------------------------------------------------------------- driver
def new_stats():
    return {"kept": 0, "rejected": 0, "oem_direct": 0, "dropped_dedup": 0,
            "dropped_filter": 0, "oem_empty": 0, "scores": []}
