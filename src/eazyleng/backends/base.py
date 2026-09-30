from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from typing import Dict, List, Mapping, Optional, Sequence

from ..exceptions import TranslationError


class Translator(ABC):
    """Interfaccia comune dei servizi di traduzione.

    Un backend deve implementare almeno :meth:`translate_batch`. I backend che
    possono tradurre in più lingue con una sola chiamata (es. un LLM)
    sovrascrivono :meth:`translate_multi`.
    """

    #: Nome usato come parte della chiave di cache.
    name: str = "base"
    #: True se il servizio riceve il testo come markup (XML/HTML escapato).
    markup: bool = False
    #: Numero massimo di testi per singola richiesta.
    max_batch_size: int = 50

    def __init__(self, language_map: Optional[Mapping[str, str]] = None):
        # Consente di rimappare i codici lingua dell'app su quelli del servizio,
        # ad esempio {"en": "EN-US"} per DeepL.
        self.language_map = {k.lower(): v for k, v in (language_map or {}).items()}

    def lang_code(self, lang: str) -> str:
        return self.language_map.get(lang.lower(), self.default_lang_code(lang))

    def default_lang_code(self, lang: str) -> str:
        return lang

    @abstractmethod
    def translate_batch(self, texts: Sequence[str], source: str, target: str) -> List[str]:
        """Traduce ``texts`` da ``source`` a ``target`` mantenendo l'ordine."""

    def translate_multi(self, texts: Sequence[str], source: str, targets: Sequence[str]) -> Dict[str, List[str]]:
        """Traduce ``texts`` in tutte le lingue ``targets``."""
        result: Dict[str, List[str]] = {}
        for target in targets:
            out: List[str] = []
            for i in range(0, len(texts), self.max_batch_size):
                chunk = list(texts[i:i + self.max_batch_size])
                translated = self.translate_batch(chunk, source, target)
                if len(translated) != len(chunk):
                    raise TranslationError(
                        f"{self.name}: attese {len(chunk)} traduzioni per '{target}', ricevute {len(translated)}"
                    )
                out.extend(translated)
            result[target] = out
        return result


class HTTPTranslator(Translator):
    """Base per i backend REST, senza dipendenze esterne (usa urllib)."""

    def __init__(self, *, timeout: float = 30.0, max_retries: int = 3, **kwargs):
        super().__init__(**kwargs)
        self.timeout = timeout
        self.max_retries = max_retries

    def _post(self, url: str, *, data=None, json_body=None, headers: Optional[Mapping[str, str]] = None):
        hdrs = {"Accept": "application/json", "User-Agent": "eazyleng"}
        hdrs.update(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        else:
            body = urllib.parse.urlencode(data or {}, doseq=True).encode("utf-8")
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"

        delay = 1.0
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                retryable = exc.code == 429 or exc.code >= 500
                if retryable and attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                detail = exc.read().decode("utf-8", "replace")[:500]
                raise TranslationError(f"{self.name}: HTTP {exc.code} - {detail}") from exc
            except urllib.error.URLError as exc:
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise TranslationError(f"{self.name}: errore di rete - {exc.reason}") from exc
        raise TranslationError(f"{self.name}: tentativi esauriti")  # pragma: no cover
