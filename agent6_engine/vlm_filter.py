"""VLM-Download-Filter — der inhaltliche Scope-Gate.

Prüft JEDES geerntete Bild gegen seine Zielklasse: ist das eine kettengetriebene,
in-scope Maschine des erwarteten Patterns? Verwirft Turbinen, Lokomotiven,
Fabrikhallen, Logos, Personen-Porträts, unrelated PR-Fotos — also genau das
Rauschen, das Bildsuche/OEM-Seiten mitliefern und das kein URL-Filter erkennt.

Verhalten:
- kein ANTHROPIC_API_KEY oder Fehler -> (True, "vlm-aus/fehler"): fail-open, blockt nichts.
- aktiv nur, wenn cfg['harvest']['vlm_filter'] = true.
Braucht: pip install anthropic ; ENV ANTHROPIC_API_KEY.
"""
from __future__ import annotations
import os, io, json, base64

_MEDIA = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def _b64(path):
    with open(path, "rb") as f:
        raw = f.read()
    ext = path.rsplit(".", 1)[-1].lower()
    return base64.standard_b64encode(raw).decode(), _MEDIA.get(ext, "image/jpeg")


def _rubric(cls, patterns):
    p = patterns.get(cls) if patterns else None
    hint = ""
    if p is not None:
        terms = getattr(p, "text_terms", None)
        if terms:
            hint = f" Merkmale dieser Klasse: {terms}."
    if cls == "out_scope":
        return "eine NICHT gesuchte Maschine (Rad-/AGV/SPMT/Schreitbagger/TBM/Sewer)"
    return (f"eine kettengetriebene (Raupen-)Maschine mit Fernsteuerung/HMI der Klasse {cls}.{hint}")


def keep_image(path, cls, patterns, cfg) -> tuple[bool, str]:
    if not cfg["harvest"].get("vlm_filter"):
        return True, "vlm-aus"
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return True, "kein-key"
    try:
        import anthropic
        data, media = _b64(path)
        model = cfg["harvest"].get("vlm_model", "claude-haiku-4-5-20251001")
        client = anthropic.Anthropic(api_key=key)
        prompt = (
            "Du bist ein strenger Bild-Klassifikator für Industriemaschinen. "
            f"Erwartet wird {_rubric(cls, patterns)} "
            "Antworte NUR als JSON {\"keep\": true|false, \"reason\": \"kurz\"}. "
            "keep=false bei: Turbine, Lokomotive, Fabrikhalle/Gebäude, Logo, Person-Porträt, "
            "Diagramm, Rad-getriebener Maschine oder wenn keine Kette/kein Fahrwerk erkennbar."
        )
        msg = client.messages.create(
            model=model, max_tokens=120,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}},
                {"type": "text", "text": prompt}]}])
        txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return parse_verdict(txt)
    except Exception as e:
        return True, f"vlm-fehler:{type(e).__name__}"


def keep_candidate(name, text, cls, patterns, cfg) -> tuple[bool, str]:
    """Text-Scope-Gate für Discovery: Firma+Snippet gegen Klasse prüfen (kein Bild).
    Kein Key -> (True,'kein-key'): Gate inaktiv, discover() warnt dann."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return True, "kein-key"
    try:
        import anthropic
        model = cfg["harvest"].get("vlm_model", "claude-haiku-4-5-20251001")
        client = anthropic.Anthropic(api_key=key)
        prompt = (
            f"Firma: {name}\nText: {text}\n\n"
            f"Ist das ein Hersteller einer kettengetriebenen (Raupen-)Maschine mit "
            f"Fernsteuerung/HMI, passend zu Klasse {cls}? "
            "Lehne ab: Radmaschinen, Aggregatoren/Händler, AGV/SPMT/Schreitbagger/TBM/"
            "Sewer-Inspektion, reine Software/Beratung. "
            'Antworte NUR JSON {"keep": true|false, "reason": "kurz"}.'
        )
        msg = client.messages.create(model=model, max_tokens=120,
                                     messages=[{"role": "user", "content": prompt}])
        txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return parse_verdict(txt)
    except Exception as e:
        return True, f"vlm-fehler:{type(e).__name__}"


def parse_verdict(txt: str) -> tuple[bool, str]:
    """Trennt Parsing vom Netzwerk (offline testbar)."""
    s = txt.strip()
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        try:
            d = json.loads(s[a:b + 1])
            return bool(d.get("keep", True)), str(d.get("reason", ""))[:80]
        except Exception:
            pass
    low = s.lower()
    if '"keep": false' in low or "keep=false" in low or low.startswith("false"):
        return False, "geparst:false"
    return True, "unklar-behalten"
