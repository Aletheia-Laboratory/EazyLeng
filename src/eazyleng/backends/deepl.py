from __future__ import annotations

import os
from typing import List, Optional, Sequence

from ..exceptions import ConfigurationError
from .base import HTTPTranslator

# DeepL richiede la variante regionale per alcune lingue di destinazione.
_DEEPL_TARGET_DEFAULTS = {"en": "EN-GB", "pt": "PT-PT", "zh": "ZH-HANS"}


class DeepLTranslator(HTTPTranslator):
    """Backend DeepL (https://www.deepl.com/docs-api).

    La API key si passa come argomento o tramite ``DEEPL_API_KEY``. Le chiavi
    del piano gratuito (che terminano con ``:fx``) usano automaticamente
    l'endpoint ``api-free``.
    """

    name = "deepl"
    markup = True

    def __init__(self, api_key: Optional[str] = None, *, formality: Optional[str] = None,
                 glossary_id: Optional[str] = None, base_url: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or os.environ.get("DEEPL_API_KEY")
        if not self.api_key:
            raise ConfigurationError("DeepL: API key mancante (argomento api_key o variabile DEEPL_API_KEY)")
        free = self.api_key.endswith(":fx")
        self.base_url = base_url or ("https://api-free.deepl.com" if free else "https://api.deepl.com")
        self.formality = formality
        self.glossary_id = glossary_id

    def default_lang_code(self, lang: str) -> str:
        return _DEEPL_TARGET_DEFAULTS.get(lang.lower(), lang.upper())

    def translate_batch(self, texts: Sequence[str], source: str, target: str) -> List[str]:
        body = {
            "text": list(texts),
            # La lingua sorgente non ammette varianti regionali.
            "source_lang": source.split("-")[0].upper(),
            "target_lang": self.lang_code(target),
            "tag_handling": "xml",
            "ignore_tags": ["x"],
            "preserve_formatting": True,
        }
        if self.formality:
            body["formality"] = self.formality
        if self.glossary_id:
            body["glossary_id"] = self.glossary_id
        data = self._post(
            f"{self.base_url}/v2/translate",
            json_body=body,
            headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
        )
        return [t["text"] for t in data["translations"]]
