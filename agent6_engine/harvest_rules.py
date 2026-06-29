"""Bildsuche-Training -> maschinell ausführbare Harvest-Regeln.

Statt eines manuellen Merkblatts wird das Sheet zur Konfiguration:
- Ausschluss-Keywords (Standard '-hobby -toy -rc car' ...)
- Kabel-Keyword-Pflicht je Pattern (P1/P2/P3/P7/P13)
- 'Text-only'-Signale, die in der Bildsuche zu schwach sind (überspringen)
- Operator-Positions-Filter (P1 behind / P2 beside / P3 far / P16 none)
- Primär-Query-Templates je Pattern
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


@dataclass
class HarvestRules:
    exclusion_keywords: list[str] = field(default_factory=list)
    cable_keyword_patterns: list[str] = field(default_factory=list)
    text_only_patterns: list[str] = field(default_factory=list)
    operator_filter: dict[str, str] = field(default_factory=dict)
    primary_query: dict[str, str] = field(default_factory=dict)
    raw_active: list[tuple] = field(default_factory=list)

    def query_for(self, pattern: str, oem: str, base_query: str | None) -> str:
        """Baut die Bildsuche-Query: OEM-Name + Pattern-Template + Operator + Kabel + Ausschluss."""
        parts = [oem]
        if base_query:
            parts.append(str(base_query))
        if pattern in self.cable_keyword_patterns:
            parts.append("cable wired control")
        if pattern in self.operator_filter:
            parts.append(self.operator_filter[pattern])
        q = " ".join(p for p in parts if p)
        if self.exclusion_keywords:
            q += " " + " ".join(self.exclusion_keywords)
        return q.strip()

    def is_text_only(self, pattern: str) -> bool:
        return pattern in self.text_only_patterns


# Fallback-Defaults, falls das Sheet fehlt (entsprechen Regel 4.04.2026)
_DEFAULT_EXCLUSION = ["-hobby", "-toy", "-rc", "-car", "-stock", "-logo"]
_DEFAULT_CABLE = ["P1", "P2", "P3", "P7", "P13"]
_DEFAULT_OPERATOR = {"P1": "operator walking behind", "P2": "operator beside machine",
                     "P3": "operator far tethered", "P16": "no operator autonomous"}


def _patterns_in(text):
    return re.findall(r"P\d+", str(text or ""))


def read_rules(wb, cfg) -> HarvestRules:
    name = cfg["master"]["bildsuche_sheet"]
    rules = HarvestRules(exclusion_keywords=list(_DEFAULT_EXCLUSION),
                         cable_keyword_patterns=list(_DEFAULT_CABLE),
                         operator_filter=dict(_DEFAULT_OPERATOR))
    if name not in wb.sheetnames:
        return rules
    ws = wb[name]
    hr = cfg["master"]["bildsuche_header_row"]
    for r in range(hr + 1, ws.max_row + 1):
        signal = ws.cell(r, 1).value
        descr = ws.cell(r, 2).value
        relevance = ws.cell(r, 3).value
        status = _norm(ws.cell(r, 4).value)
        if not signal:
            continue
        s_norm = _norm(signal); d_norm = _norm(descr); rel = _norm(relevance)
        if status and status not in ("aktiv", ""):
            continue  # veraltete Regeln ignorieren
        rules.raw_active.append((str(signal), str(descr), str(relevance)))

        # Ausschluss-Keywords aus 'standardisieren'-Regel ziehen
        if "ausschluss" in s_norm or "ausschluss" in d_norm:
            for kw in re.findall(r"-[a-z][a-z0-9\- ]+", d_norm):
                for tok in kw.split():
                    if tok.startswith("-") and tok not in rules.exclusion_keywords:
                        rules.exclusion_keywords.append(tok)
        # 'Text-only' / 'nur Text' -> Pattern in der Bildsuche überspringen
        if "text only" in rel or "text-priorität" in rel or "nur text" in d_norm or "text only" in d_norm:
            for p in _patterns_in(relevance) + _patterns_in(descr):
                if p not in rules.text_only_patterns:
                    rules.text_only_patterns.append(p)
        # Primär-Query-Templates ('Query: ...')
        if d_norm.startswith("query:") or "query:" in d_norm:
            m = re.search(r"query:\s*'?([^'\n]+)", str(descr), re.I)
            if m:
                for p in _patterns_in(relevance) or _patterns_in(signal):
                    rules.primary_query.setdefault(p, m.group(1).strip())
        # Operator-Positions-Signale
        if "operator" in s_norm:
            for p in _patterns_in(signal):
                if "hinter" in s_norm or "behind" in s_norm:
                    rules.operator_filter[p] = "operator walking behind"
                elif "neben" in s_norm or "beside" in s_norm:
                    rules.operator_filter[p] = "operator beside machine"
                elif "entfernt" in s_norm or "far" in s_norm:
                    rules.operator_filter[p] = "operator far tethered"
                elif "kein operator" in s_norm or "no operator" in s_norm:
                    rules.operator_filter[p] = "no operator autonomous"
    return rules
