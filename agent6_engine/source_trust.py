"""Quellen-Vertrauen — eine Wahrheit fuer Harvester, Resolver und Quality-Gate.

Leitprinzip (Pierres Vorgabe): Das Modell soll die Zehntausenden Marktplatz-/Handels-
Aggregatoren, Social- und Stockfoto-Seiten HART IGNORIEREN und sich auf vertrauenswuerdige
Quellen (OEM-direkt, Fachpresse, Register/Behoerden, Wissenschaft) fokussieren.
Trust vor Volumen: lieber wenige belastbare Treffer als viel 'cheap content'.

Warum das noetig ist: Die Bildsuche rankt nach SEO/Domain-Autoritaet, nicht nach Trust.
Aggregatoren (Alibaba, made-in-china, machinerytrader) und Social (TikTok, Facebook)
gewinnen diesen Wettbewerb strukturell — deshalb muessen wir sie explizit ausschliessen.
"""
from urllib.parse import urlparse

# --- Nie verwertbar: Social, Foren, Stockfotos ---
SOCIAL_STOCK = (
    "pinterest.", "tiktok.", "facebook.", "fb.watch", "instagram.", "youtube.", "youtu.be",
    "twitter.", "reddit.", "redd.it", "linkedin.", "vk.com", "weibo.", "flickr.",
    "tumblr.", "quora.",
    "shutterstock.", "istockphoto.", "gettyimages.", "alamy.", "dreamstime.", "123rf.",
    "depositphotos.", "stock.adobe.", "adobestock.", "wikipedia.", "wikimedia.",
)

# --- Marktplaetze / Handels-Aggregatoren: viele Bilder, aber NIE die OEM-Seite ---
MARKETPLACE = (
    "alibaba.", "aliexpress.", "made-in-china.", "indiamart.", "amazon.", "ebay.",
    "etsy.", "wish.com", "dhgate.", "tradeindia.", "globalsources.", "ec21.", "tradekey.",
    "machinerytrader.", "marketbook.", "mascus.", "machineryzone.", "exapro.",
    "europages.", "directindustry.", "ironplanet.", "govplanet.", "ritchiespecs.",
    "equipmenttrader.", "trademachines.", "truckpaper.", "forestrytrader.",
    "mylittlesalesman.", "cranenetwork.", "plantandequipment.", "agriaffaires.",
    "truck1.", "autoline.", "rockanddirt.", "sandhills.", "kijiji.", "gumtree.",
    "craigslist.", "houseofcontractors.", "masterwholesale.", "trademe.", "olx.",
    "alfagomma", "surplusrecord.",
)

# --- Thumbnail-/Bild-CDNs: dahinter steckt keine lesbare Produktseite ---
CDN = (
    "ytimg.", "ggpht.", "pinimg.", "fbcdn.", "twimg.", "i.redd.", "wp.com",
    "staticflickr.", "cloudfront.", "blogspot.", "wixstatic.", "squarespace-cdn.",
    "cdn.shopify.", "shopifycdn.", "alicdn.", "aliexpress-media.", "hearstapps.",
    "sanity.io", "lookaside.fbsbx.", "media.sandhills.", "imgur.", "gstatic.",
    "akamaized.", "cdninstagram.",
)

# --- OEM-Allowlist: bekannte Hersteller-Domains (Score 3). Waechst mit den Reviews. ---
# Nur hier eintragen, was sicher eine Herstellerseite ist. Bewusst konservativ.
OEM_ALLOWLIST = (
    "liebherr.", "banditchippers.", "toro.", "vermeer.", "rayco.", "carltonsp.",
    "imergroup.", "ensigneq.", "canycom.", "cormidi.", "hinowa.", "merlo.",
    "takeuchi-us.", "kubota.", "bobcat.", "avant.", "prinoth.", "seppi.",
)

# --- Fachpresse / Branchenmedien (Score 2, aber keine Primaerquelle) ---
PRESS = (
    "forconstructionpros.", "khl.com", "internationalconstruction", "ieee.",
    "acm.org", "sciencedirect.", "springer.", "futurefarming.", "agriland.",
    "landscapeprofessionals.", "recyclingtoday.", "forestryjournal.",
)

LOW_TRUST = SOCIAL_STOCK + MARKETPLACE + CDN


def domain(u):
    try:
        d = urlparse(u).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def is_social_or_stock(url):
    d = domain(url)
    return bool(d) and any(n in d for n in SOCIAL_STOCK)


def is_marketplace(url):
    d = domain(url)
    return bool(d) and any(n in d for n in MARKETPLACE)


def is_cdn(url):
    d = domain(url)
    return bool(d) and any(n in d for n in CDN)


def is_low_trust(url) -> bool:
    """True fuer Social/Stock, Marktplatz/Aggregator, Thumbnail-CDN — und fuer alles
    ohne aufloesbare Domain. Diese Quellen werden am Harvest verworfen."""
    d = domain(url)
    if not d:
        return True
    return any(n in d for n in LOW_TRUST)


def block_reason(url) -> str:
    """Kategorie, warum eine Quelle geblockt wird (fuer transparente Metriken)."""
    if not domain(url):
        return "keine-domain"
    if is_social_or_stock(url):
        return "social/stock"
    if is_marketplace(url):
        return "marktplatz"
    if is_cdn(url):
        return "cdn/thumbnail"
    return "ok"


def is_oem(url) -> bool:
    d = domain(url)
    return bool(d) and any(o in d for o in OEM_ALLOWLIST)


def source_score(url) -> int:
    """1 = cheap (Aggregator/Marktplatz/Social/CDN), 2 = Fachpresse/unbekannt (nicht geblockt),
    3 = OEM-direkt (Allowlist). Basis fuer die Quellen-Score-Metrik im Quality-Gate."""
    if is_low_trust(url):
        return 1
    if is_oem(url):
        return 3
    # bekannte Presse ODER unbekannte, nicht geblockte Domain -> Fachquelle-Default
    return 2
