from __future__ import annotations

import os
from typing import List, Optional, Sequence

from .base import HTTPTranslator


class LibreTranslateTranslator(HTTPTranslator):
    """Backend LibreTranslate (open source, anche self-hosted).

    URL e chiave si passano come argomenti o tramite ``LIBRETRANSLATE_URL`` e
    ``LIBRETRANSLATE_API_KEY``.
    """

    name = "libretranslate"
    markup = True

    def __init__(self, url: Optional[str] = None, api_key: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.url = (url or os.environ.get("LIBRETRANSLATE_URL") or "http://localhost:5000").rstrip("/")
        self.api_key = api_key or os.environ.get("LIBRETRANSLATE_API_KEY")

    def translate_batch(self, texts: Sequence[str], source: str, target: str) -> List[str]:
        body = {
            "q": list(texts),
            "source": self.lang_code(source),
            "target": self.lang_code(target),
            "format": "html",
        }
        if self.api_key:
            body["api_key"] = self.api_key
        data = self._post(f"{self.url}/translate", json_body=body)
        translated = data["translatedText"]
        return translated if isinstance(translated, list) else [translated]
