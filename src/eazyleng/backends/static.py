from __future__ import annotations

from typing import Callable, List, Mapping, Optional, Sequence

from ..exceptions import TranslationError
from .base import Translator


class DictionaryTranslator(Translator):
    """Traduzioni fornite a mano: ``{lingua: {testo_italiano: traduzione}}``.

    Utile per test, per termini già validati o come fallback offline. Se un
    testo manca si usa ``fallback`` (un altro Translator) oppure si solleva
    un errore.
    """

    name = "dictionary"

    def __init__(self, entries: Mapping[str, Mapping[str, str]], fallback: Optional[Translator] = None, **kwargs):
        super().__init__(**kwargs)
        self.entries = {lang.lower(): dict(m) for lang, m in entries.items()}
        self.fallback = fallback
        if fallback is not None:
            self.markup = fallback.markup

    def translate_batch(self, texts: Sequence[str], source: str, target: str) -> List[str]:
        table = self.entries.get(target.lower(), {})
        missing = [t for t in texts if t not in table]
        extra = {}
        if missing:
            if self.fallback is None:
                raise TranslationError(f"dictionary: nessuna traduzione '{target}' per {missing[0]!r}")
            extra = dict(zip(missing, self.fallback.translate_batch(missing, source, target)))
        return [table.get(t, extra.get(t)) for t in texts]


class FunctionTranslator(Translator):
    """Adatta una qualsiasi funzione ``f(testo, source, target) -> str``."""

    name = "function"

    def __init__(self, func: Callable[[str, str, str], str], *, markup: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.func = func
        self.markup = markup

    def translate_batch(self, texts: Sequence[str], source: str, target: str) -> List[str]:
        return [self.func(t, source, target) for t in texts]
