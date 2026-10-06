from agent6_engine import phash as P
from agent6_engine import image_search_harvester as H

def test_hamming():
    assert P.hamming("ffffffffffffffff", "ffffffffffffffff") == 0
    assert P.hamming("0000000000000000", "0000000000000001") == 1
    assert P.hamming("abc", "") is None          # ungleiche/leere Eingabe

def test_duplicate_of():
    seen = ["ffffffffffffffff"]
    assert P.duplicate_of("fffffffffffffffe", seen, threshold=5) == "ffffffffffffffff"  # 1 bit
    assert P.duplicate_of("0000000000000000", seen, threshold=5) is None                # weit weg
    assert P.duplicate_of("", seen) is None

def test_phash_bytes_gleiches_bild():
    from PIL import Image
    import io
    def png(color):
        b = io.BytesIO(); Image.new("RGB", (64, 64), color).save(b, "PNG"); return b.getvalue()
    h1 = P.phash_bytes(png((10, 120, 200)))
    h2 = P.phash_bytes(png((10, 120, 200)))
    assert h1 and h1 == h2                        # identisches Bild -> identischer Hash
    assert P.phash_bytes(b"not an image") is None # fail-open

def test_fetch_image_hash_injiziert():
    from PIL import Image
    import io
    b = io.BytesIO(); Image.new("RGB", (32, 32), (0, 0, 0)).save(b, "PNG")
    data = b.getvalue()
    assert P.fetch_image_hash("http://x/y.png", fetch=lambda u: data) == P.phash_bytes(data)
    assert P.fetch_image_hash("http://x/y.png", fetch=lambda u: (_ for _ in ()).throw(IOError())) is None

class FakePattern:
    def __init__(self, q): self.img_query = q; self.text_terms = ""; self.segment = "seg"
class FakeSearcher:
    def __init__(self, r): self.results = r
    def search(self, q, n=15): return self.results
class FakeWriter:
    enabled = True
    def __init__(self): self.written = []
    def existing_urls(self): return set()
    def existing_hashes(self): return set()
    def write(self, recs): self.written.extend(recs); return len(recs)

def test_harvest_phash_dedup(tmp_path, monkeypatch):
    # zwei verschiedene URLs, gleiches Bild (gleicher pHash) -> 1 neu, 1 dup_img
    hashes = {"https://a.com/1.jpg": "ffffffffffffffff", "https://b.com/2.jpg": "ffffffffffffffff"}
    monkeypatch.setattr(H._phash, "fetch_image_hash", lambda url, *a, **k: hashes.get(url))
    s = FakeSearcher([{"url": "https://a.com/1.jpg", "source": "a"},
                      {"url": "https://b.com/2.jpg", "source": "b"}])
    res = H.harvest({"harvest": {"phash_dedup": True}}, {"P4": FakePattern("rig")},
                    per_pattern=10, searcher=s, writer=FakeWriter(),
                    manifest_path=str(tmp_path / "m.json"))
    assert res["new"] == 1 and res["dup_img"] == 1
