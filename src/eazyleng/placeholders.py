"""Protezione dei placeholder durante la traduzione.

Stringhe come ``{nome}``, ``%(count)d``, ``%s``, ``{{ var }}`` o tag HTML non
devono essere tradotte né alterate. Prima dell'invio al servizio vengono
sostituite da marcatori ``<x id="N"/>`` e ripristinate al ritorno.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .exceptions import PlaceholderError

# L'ordine conta: i pattern più specifici vanno prima.
_PATTERNS = [
    r"\{\{.*?\}\}",                         # {{ jinja / handlebars }}
    r"\{[A-Za-z0-9_.\[\]]*(?:![rsa])?(?::[^{}]*)?\}",  # {nome}, {0}, {prezzo:.2f}
    r"%\([A-Za-z0-9_]+\)[-#0 +]*\d*(?:\.\d+)?[sdifFeEgGxXor%]",  # %(nome)s
    r"%[-#0 +]*\d*(?:\.\d+)?[sdifFeEgGxXo]",  # %s, %d, %.2f
]
# Pattern opzionale per i placeholder stile Laravel (":nome"), da passare in
# ``extra_patterns``: non è attivo di default perché può colpire testo normale.
LARAVEL_PATTERN = r"(?<![\w/]):[A-Za-z_][A-Za-z0-9_]*"
_HTML_TAG = r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>"

_MARKER_RE = re.compile(r"<\s*x\s+id\s*=\s*[\"'](\d+)[\"']\s*/?\s*>(?:\s*</\s*x\s*>)?")


@dataclass
class MaskedText:
    """Testo con placeholder sostituiti da marcatori."""

    text: str
    placeholders: List[str] = field(default_factory=list)
    markup: bool = False

    def unmask(self, translated: str) -> str:
        found = set()

        def _restore(match: re.Match) -> str:
            idx = int(match.group(1))
            if idx >= len(self.placeholders):
                raise PlaceholderError(f"Marcatore sconosciuto <x id=\"{idx}\"/> nella traduzione: {translated!r}")
            found.add(idx)
            # Il placeholder viene reinserito "grezzo": va protetto dall'unescape.
            return f"\x00{idx}\x00"

        restored = _MARKER_RE.sub(_restore, translated)
        missing = set(range(len(self.placeholders))) - found
        if missing:
            lost = ", ".join(self.placeholders[i] for i in sorted(missing))
            raise PlaceholderError(f"Placeholder persi nella traduzione ({lost}): {translated!r}")
        if self.markup:
            restored = html.unescape(restored)
        return re.sub(r"\x00(\d+)\x00", lambda m: self.placeholders[int(m.group(1))], restored)


def mask(text: str, *, protect: bool = True, protect_html: bool = True, markup: bool = False,
         extra_patterns: Sequence[str] = ()) -> MaskedText:
    """Sostituisce i placeholder di ``text`` con marcatori ``<x id="N"/>``.

    Con ``markup=True`` il testo restante viene escapato come XML/HTML, così
    i servizi che lavorano in modalità markup (DeepL, Google, LibreTranslate)
    lasciano intatti i marcatori. Con ``protect=False`` nessun placeholder
    viene protetto (viene solo applicato l'eventuale escape).

    I messaggi ICU (``{n, plural, one {...} other {...}}``, usati da next-intl
    e react-intl) vengono protetti nella struttura, mentre il testo dei rami
    resta traducibile.
    """
    patterns = list(extra_patterns) + _PATTERNS if protect else []
    if protect and protect_html:
        patterns.append(_HTML_TAG)
    regex = re.compile("|".join(f"(?:{p})" for p in patterns) or r"(?!)")

    # Span da proteggere: prima la sintassi ICU, poi i placeholder nei tratti liberi.
    spans: List[Tuple[int, int]] = []
    icu = _icu_spans(text) if protect else []
    pos = 0
    for start, end in icu + [(len(text), len(text))]:
        spans.extend(m.span() for m in regex.finditer(text, pos, start))
        if start < end:
            spans.append((start, end))
        pos = end

    placeholders: List[str] = []
    parts: List[str] = []
    pos = 0
    for start, end in spans:
        chunk = text[pos:start]
        parts.append(html.escape(chunk, quote=False) if markup else chunk)
        parts.append(f'<x id="{len(placeholders)}"/>')
        placeholders.append(text[start:end])
        pos = end
    tail = text[pos:]
    parts.append(html.escape(tail, quote=False) if markup else tail)
    return MaskedText("".join(parts), placeholders, markup)


# --- ICU MessageFormat --------------------------------------------------------------

_ICU_HEAD = re.compile(r"\{\s*[A-Za-z_][\w.]*\s*,\s*(plural|selectordinal|select)\s*,(?:\s*offset:\s*\d+)?")
_ICU_SELECTOR = re.compile(r"\s*(?:=\d+|[A-Za-z_]\w*)\s*\{")
_ICU_CLOSE = re.compile(r"\s*\}")


def _icu_spans(text: str) -> List[Tuple[int, int]]:
    """Intervalli di ``text`` che sono sintassi ICU (non da tradurre).

    Se il messaggio non è ICU ben formato restituisce ``[]`` e il testo viene
    trattato normalmente.
    """
    spans: List[Tuple[int, int]] = []
    i = 0
    while i < len(text):
        if text[i] == "{" and _ICU_HEAD.match(text, i):
            end = _parse_icu(text, i, spans)
            if end is None:
                return []
            i = end
        else:
            i += 1
    # Unisce gli intervalli contigui: "} other {" diventa un solo marcatore.
    merged: List[Tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _parse_icu(text: str, start: int, spans: List[Tuple[int, int]]) -> Optional[int]:
    head = _ICU_HEAD.match(text, start)
    is_plural = head.group(1) != "select"
    spans.append((start, head.end()))
    pos = head.end()
    branches = 0
    while True:
        sel = _ICU_SELECTOR.match(text, pos)
        if not sel:
            break
        spans.append((pos, sel.end()))
        j = sel.end()
        while True:
            if j >= len(text):
                return None
            ch = text[j]
            if ch == "{":
                if _ICU_HEAD.match(text, j):
                    j = _parse_icu(text, j, spans)
                    if j is None:
                        return None
                    continue
                close = text.find("}", j)
                if close == -1:
                    return None
                j = close + 1  # argomento semplice: lo gestiscono le regex
            elif ch == "#" and is_plural:
                spans.append((j, j + 1))
                j += 1
            elif ch == "}":
                spans.append((j, j + 1))
                pos = j + 1
                branches += 1
                break
            else:
                j += 1
    close = _ICU_CLOSE.match(text, pos)
    if not close or branches == 0:
        return None
    spans.append((pos, close.end()))
    return close.end()
