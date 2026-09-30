from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Union

from .backends.base import Translator
from .languages import DEFAULT_TARGETS, normalize
from .placeholders import mask


def make_key(text: str, prefix: str = "") -> str:
    """Chiave stabile per un testo: slug delle prime parole + hash breve.

    ``make_key("Benvenuto nel sito!")`` -> ``"benvenuto_nel_sito_3f9a1c2b"``
    """
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")[:40].rstrip("_")
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}{slug}_{digest}" if slug else f"{prefix}{digest}"


@dataclass
class TranslationRecord:
    """Un testo con tutte le sue traduzioni, pronto per il database."""

    key: str
    source_lang: str
    source_text: str
    translations: Dict[str, str]
    backend: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    @property
    def languages(self) -> List[str]:
        return list(self.translations)

    def get(self, lang: str, default: Optional[str] = None) -> Optional[str]:
        """Traduzione per ``lang``; se manca prova la lingua base, poi il testo sorgente."""
        lang = normalize(lang)
        if lang in self.translations:
            return self.translations[lang]
        base = lang.split("-")[0]
        if base in self.translations:
            return self.translations[base]
        return default if default is not None else self.source_text

    def __getitem__(self, lang: str) -> str:
        return self.translations[normalize(lang)]

    # --- Formati per il database -------------------------------------------------

    def to_rows(self) -> List[Dict[str, object]]:
        """Una riga per lingua (tabella normalizzata ``key, lang, text``).

        È il formato più flessibile: aggiungere una lingua non richiede di
        modificare lo schema.
        """
        return [
            {
                "key": self.key,
                "lang": lang,
                "text": text,
                "is_source": lang == self.source_lang,
                "backend": "" if lang == self.source_lang else self.backend,
                "updated_at": self.created_at,
            }
            for lang, text in self.translations.items()
        ]

    def to_columns(self, prefix: str = "text_") -> Dict[str, str]:
        """Una colonna per lingua: ``{"key": ..., "text_it": ..., "text_en": ...}``."""
        row = {"key": self.key}
        for lang, text in self.translations.items():
            row[prefix + lang.replace("-", "_").lower()] = text
        return row

    def to_dict(self) -> Dict[str, object]:
        """Struttura completa, adatta a una colonna JSON/JSONB o a un documento NoSQL."""
        return {
            "key": self.key,
            "source_lang": self.source_lang,
            "translations": dict(self.translations),
            "backend": self.backend,
            "created_at": self.created_at,
        }

    def to_json(self, **kwargs) -> str:
        """Solo la mappa ``{lingua: testo}`` in JSON (per una colonna JSON)."""
        kwargs.setdefault("ensure_ascii", False)
        return json.dumps(self.translations, **kwargs)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "TranslationRecord":
        translations = dict(data["translations"])  # type: ignore[arg-type]
        source_lang = str(data.get("source_lang", "it"))
        return cls(
            key=str(data["key"]),
            source_lang=source_lang,
            source_text=translations.get(source_lang, ""),
            translations=translations,
            backend=str(data.get("backend", "")),
            created_at=str(data.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


Items = Union[Mapping[str, str], Iterable[str]]


class EazyLeng:
    """Traduce testi italiani in tutte le lingue configurate.

    Senza ``translator`` usa il servizio configurato nell'ambiente
    (``DEEPL_API_KEY``, ``ANTHROPIC_API_KEY``, ...); si può passare anche il
    nome (``"deepl"``, ``"claude"``, ...) o un'istanza di :class:`Translator`.

    >>> from eazyleng import EazyLeng
    >>> tr = EazyLeng(targets=["en", "fr", "de"])
    >>> rec = tr.translate("Benvenuto, {nome}!", key="home.welcome")
    >>> rec.to_rows()   # pronto per INSERT
    """

    def __init__(
        self,
        translator: Union[Translator, str, None] = None,
        targets: Sequence[str] = DEFAULT_TARGETS,
        source: str = "it",
        *,
        cache: Optional[MutableMapping[str, str]] = None,
        protect_placeholders: bool = True,
        protect_html: bool = True,
        extra_patterns: Sequence[str] = (),
        key_prefix: str = "",
    ):
        if translator is None or isinstance(translator, str):
            from .backends import get_translator
            translator = get_translator(translator or "auto")
        self.translator = translator
        self.source = normalize(source)
        self.targets = [t for t in dict.fromkeys(normalize(t) for t in targets) if t != self.source]
        self.cache = cache
        self.protect_placeholders = protect_placeholders
        self.protect_html = protect_html
        self.extra_patterns = list(extra_patterns)
        self.key_prefix = key_prefix

    # --- API pubblica -------------------------------------------------------------

    def translate(self, text: str, key: Optional[str] = None, targets: Optional[Sequence[str]] = None) -> TranslationRecord:
        """Traduce un singolo testo e restituisce il record per il DB."""
        items = {key: text} if key else [text]
        return self.translate_many(items, targets=targets)[0]

    def translate_many(self, items: Items, targets: Optional[Sequence[str]] = None) -> List[TranslationRecord]:
        """Traduce più testi riducendo al minimo le chiamate al servizio.

        ``items`` può essere un dict ``{chiave: testo}`` o una lista di testi
        (le chiavi vengono generate con :func:`make_key`). I testi duplicati
        vengono tradotti una sola volta.
        """
        if isinstance(items, Mapping):
            pairs = [(str(k), v) for k, v in items.items()]
        else:
            pairs = [(make_key(t, self.key_prefix), t) for t in items]
        for _, text in pairs:
            if not isinstance(text, str):
                raise TypeError(f"Il testo da tradurre deve essere una stringa, non {type(text).__name__}")

        langs = self.resolve_targets(targets)
        unique_texts = list(dict.fromkeys(text for _, text in pairs))
        table = self._translate_texts(unique_texts, langs)

        return [
            TranslationRecord(
                key=key,
                source_lang=self.source,
                source_text=text,
                translations={self.source: text, **{lang: table[lang][text] for lang in langs}},
                backend=self.translator.name,
            )
            for key, text in pairs
        ]

    # --- Interni ------------------------------------------------------------------

    def resolve_targets(self, targets: Optional[Sequence[str]]) -> List[str]:
        if targets is None:
            return list(self.targets)
        return [t for t in dict.fromkeys(normalize(t) for t in targets) if t != self.source]

    def _cache_key(self, lang: str, text: str) -> str:
        return f"{self.translator.name}|{self.source}|{lang}|{text}"

    def _translate_texts(self, texts: List[str], langs: List[str]) -> Dict[str, Dict[str, str]]:
        table: Dict[str, Dict[str, str]] = {lang: {} for lang in langs}
        # Testi che richiedono davvero una chiamata, per lingua.
        todo: Dict[str, List[str]] = {lang: [] for lang in langs}

        for text in texts:
            for lang in langs:
                if not _needs_translation(text):
                    table[lang][text] = text
                elif self.cache is not None and self._cache_key(lang, text) in self.cache:
                    table[lang][text] = self.cache[self._cache_key(lang, text)]
                else:
                    todo[lang].append(text)

        # Raggruppa le lingue con lo stesso insieme di testi mancanti, così un
        # backend multi-lingua (es. Claude) può tradurli con una sola richiesta.
        groups: Dict[tuple, List[str]] = {}
        for lang, pending in todo.items():
            if pending:
                groups.setdefault(tuple(pending), []).append(lang)

        for pending, group_langs in groups.items():
            prepared = [self._prepare(t) for t in pending]
            out = self.translator.translate_multi([p[1].text for p in prepared], self.source, group_langs)
            for lang in group_langs:
                for text, (lead, masked, trail), translated in zip(pending, prepared, out[lang]):
                    result = lead + masked.unmask(translated.strip()) + trail
                    table[lang][text] = result
                    if self.cache is not None:
                        self.cache[self._cache_key(lang, text)] = result
        return table

    def _prepare(self, text: str):
        stripped = text.strip()
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        masked = mask(stripped, protect=self.protect_placeholders, protect_html=self.protect_html,
                      markup=self.translator.markup, extra_patterns=self.extra_patterns)
        return lead, masked, trail


_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_ONLY_PLACEHOLDERS_RE = re.compile(r"^(?:\s|\{[^{}]*\}|%\(?\w*\)?[sd]|<[^<>]+>)*$")


def _needs_translation(text: str) -> bool:
    """False per stringhe vuote, numeri, simboli o soli placeholder."""
    return bool(_LETTER_RE.search(text)) and not _ONLY_PLACEHOLDERS_RE.match(text)
