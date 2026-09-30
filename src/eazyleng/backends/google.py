from __future__ import annotations

import os
from typing import List, Optional, Sequence

from ..exceptions import ConfigurationError
from .base import HTTPTranslator


class GoogleTranslator(HTTPTranslator):
    """Backend Google Cloud Translation (API v2 con API key).

    La API key si passa come argomento o tramite ``GOOGLE_TRANSLATE_API_KEY``.
    """

    name = "google"
    markup = True
    max_batch_size = 128

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or os.environ.get("GOOGLE_TRANSLATE_API_KEY")
        if not self.api_key:
            raise ConfigurationError(
                "Google: API key mancante (argomento api_key o variabile GOOGLE_TRANSLATE_API_KEY)"
            )

    def translate_batch(self, texts: Sequence[str], source: str, target: str) -> List[str]:
        data = self._post(
            "https://translation.googleapis.com/language/translate/v2",
            json_body={
                "q": list(texts),
                "source": self.lang_code(source),
                "target": self.lang_code(target),
                "format": "html",
            },
            headers={"X-Goog-Api-Key": self.api_key},
        )
        return [t["translatedText"] for t in data["data"]["translations"]]
