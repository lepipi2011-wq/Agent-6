"""Konnektor-Interface — kapselt die Eigenheiten jeder Quelle weg.

Jede API/Quelle spricht anders (SPARQL, REST, SOAP, Einzel-Lookup). Alle
Konnektoren liefern aber dieselbe Struktur: eine Liste von Claims
(predicate, value, source_url, source_type, confidence). So bleibt der
Verifikations-Loop quell-agnostisch.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from abc import ABC, abstractmethod


@dataclass
class ClaimDict:
    predicate: str
    value: str | None
    source_url: str | None = None
    source_type: str = "unknown"
    confidence: float = 0.6
    extra: dict = field(default_factory=dict)


class Connector(ABC):
    name: str = "base"
    source_type: str = "unknown"
    is_primary: bool = False
    needs_key: bool = False

    @abstractmethod
    def fetch(self, *, name: str, country: str | None = None, **kw) -> list[ClaimDict]:
        """Fragt die Quelle ab und gibt Claims zurück. Leere Liste = kein Treffer."""
        raise NotImplementedError

    # Hilfsfunktion für Offline-Tests: parse trennt Netzwerk von Logik.
    def parse(self, payload) -> list[ClaimDict]:
        return []
