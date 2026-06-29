"""Quality-Gate für den Harvest-Batch (deine Regel)."""
from __future__ import annotations


def evaluate(stats: dict, qg: dict, hypothesis: str = "") -> dict:
    kept = stats["kept"]; rejected = stats["rejected"]
    yield_ = kept / max(1, kept + rejected)
    oem_share = min(1.0, stats["oem_direct"] / max(1, kept))  # Dedup senkt kept -> clampen
    score = (sum(stats["scores"]) / len(stats["scores"])) if stats["scores"] else 0.0
    breaches = [yield_ < qg["yield_min"], oem_share < qg["oem_direct_min"], score < qg["score_min"]]
    stop = sum(breaches) >= 2

    print(f"\n— Quality-Gate (Harvest) — Hypothese: {hypothesis or '—'}")
    print(f"  Yield {yield_*100:.0f}% | OEM-direkt {oem_share*100:.0f}% | Quellen-Score {score:.2f}")
    print(f"  Bilder behalten {kept} | verworfen {rejected} "
          f"(Dedup {stats['dropped_dedup']} / gefiltert {stats['dropped_filter']}) "
          f"| OEMs ohne Treffer {stats['oem_empty']}")
    if stop:
        vor = []
        if yield_ < qg["yield_min"]:
            vor.append("Query/Quellen-Set wechseln (mehr OEM-direkt, weniger Bildsuche)")
        if oem_share < qg["oem_direct_min"]:
            vor.append("OEM-Domains pflegen / Produktseiten-Crawl priorisieren")
        if score < qg["score_min"]:
            vor.append("Aggregator-Quellen drosseln, Primärquellen erzwingen")
        print(f"  STOP. \"Yield {yield_*100:.0f}%, OEM-direkt {oem_share*100:.0f}%, "
              f"Score {score:.2f}. Sättigung. Vorschlag: {'; '.join(vor)}\"")
    return {"yield": yield_, "oem_direct_share": oem_share, "score": score, "stop": stop}
