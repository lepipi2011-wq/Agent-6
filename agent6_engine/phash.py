"""Perzeptueller Bild-Hash (pHash) — erkennt 'gleiches Bild, andere URL/Domain'.

Ergänzt die URL-Normalisierung (die nur identische Links fängt): zwei verschiedene URLs, die
dasselbe Foto zeigen, bekommen denselben pHash und werden als Dublette erkannt.

Fail-open: lässt sich ein Bild nicht laden/hashen, blockt es NIE (gibt None zurück).
Braucht imagehash + Pillow (in requirements). Rein + offline testbar (hamming/duplicate_of).
"""
from __future__ import annotations
import io


def phash_bytes(data) -> str | None:
    """pHash-Hex eines Bildes aus Bytes. None bei Fehler/kein Bild."""
    try:
        import imagehash
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            return str(imagehash.phash(im))
    except Exception:
        return None


def fetch_image_hash(url, fetch=None, timeout=15) -> str | None:
    """Lädt das Bild (eigener fetch injizierbar) und gibt den pHash zurück. None = fail-open."""
    try:
        if fetch is not None:
            data = fetch(url)
        else:
            import requests
            data = requests.get(url, timeout=timeout).content
        return phash_bytes(data) if data else None
    except Exception:
        return None


def hamming(a, b) -> int | None:
    """Hamming-Distanz zweier gleich langer Hex-Hashes. None bei leerer/ungleicher Eingabe."""
    if not a or not b or len(a) != len(b):
        return None
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except Exception:
        return None


def duplicate_of(h, seen, threshold=5):
    """Erster bekannter Hash mit Distanz <= threshold zu h (= Dublette), sonst None.
    threshold 0 = pixelgleich; ~5 fängt Reskalierung/Rekompression, ohne verschiedene Maschinen zu mischen."""
    if not h:
        return None
    for s in seen:
        d = hamming(h, s)
        if d is not None and d <= threshold:
            return s
    return None
