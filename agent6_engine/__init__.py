"""Agent 6 — Industrialisierungs-Engine.

Modul-Architektur (kein Colab): liest den Master mit seiner Struktur,
erntet OEM-direkte Bilder leakage-sicher und legt sie für das
grouped-OEM-Split-Training (Scope-Gate / Pattern-Klassifikation) ab.
"""
__version__ = "0.1.0"

# .env einmalig beim Paket-Import laden, damit ALLE Module (auch die ohne
# load_config, z.B. image_search_harvester, query_repo) die Keys sehen.
try:
    from dotenv import load_dotenv as _ld
    _ld()
except Exception:
    pass
