from __future__ import annotations

import json
from typing import Dict, List, Optional, Sequence

from ..exceptions import ConfigurationError, TranslationError
from ..languages import language_name
from .base import Translator

_SYSTEM_PROMPT = """You are a professional software localizer. You translate user-interface \
strings and content for a web application from {source} into other languages.

Rules:
- Translate the meaning naturally for native speakers, keeping the tone and register of the source.
- Markers like <x id="0"/> stand for placeholders and markup: copy every marker exactly once, \
unchanged, into each translation, moving it only if the target grammar requires it.
- Keep line breaks, leading/trailing spaces and punctuation style consistent with the source.
- Never add explanations, quotes or notes: return only the translations in the requested JSON format.{context}"""


class ClaudeTranslator(Translator):
    """Backend basato su Claude (Anthropic API).

    Traduce ogni blocco di testi in *tutte* le lingue con una sola richiesta e
    accetta un contesto libero (dominio, tono, glossario) che migliora la resa.
    Richiede ``pip install eazyleng[claude]`` e ``ANTHROPIC_API_KEY`` (o un
    profilo ``ant auth login``).

    Con ``fallbacks=True`` (default) viene abilitato il fallback lato server:
    se il modello rifiuta la richiesta, l'API la ripete su un altro modello.
    """

    name = "claude"
    max_batch_size = 25

    def __init__(self, *, model: str = "claude-opus-5-5", api_key: Optional[str] = None,
                 context: Optional[str] = None, effort: Optional[str] = None,
                 fallbacks: bool = True, max_tokens: int = 16000, client=None, **kwargs):
        super().__init__(**kwargs)
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - dipende dall'ambiente
                raise ConfigurationError("Installa il pacchetto 'anthropic': pip install eazyleng[claude]") from exc
            client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.client = client
        self.model = model
        self.context = context
        self.effort = effort
        self.fallbacks = fallbacks
        self.max_tokens = max_tokens

    def translate_batch(self, texts: Sequence[str], source: str, target: str) -> List[str]:
        return self.translate_multi(texts, source, [target])[target]

    def translate_multi(self, texts: Sequence[str], source: str, targets: Sequence[str]) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {t: [] for t in targets}
        for i in range(0, len(texts), self.max_batch_size):
            chunk = list(texts[i:i + self.max_batch_size])
            for target, values in self._translate_chunk(chunk, source, targets).items():
                result[target].extend(values)
        return result

    def _translate_chunk(self, texts: List[str], source: str, targets: Sequence[str]) -> Dict[str, List[str]]:
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "integer"}, **{t: {"type": "string"} for t in targets}},
                        "required": ["id", *targets],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        }
        langs = ", ".join(f"{t} ({language_name(t)})" for t in targets)
        payload = json.dumps([{"id": n, "text": t} for n, t in enumerate(texts)], ensure_ascii=False)
        context = f"\n\nApplication context:\n{self.context}" if self.context else ""

        params = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=_SYSTEM_PROMPT.format(source=language_name(source), context=context),
            messages=[{
                "role": "user",
                "content": f"Translate each item's text into: {langs}.\n"
                           f"Return one object per id, with one field per language code.\n\n{payload}",
            }],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        if self.effort:
            params["output_config"]["effort"] = self.effort

        if self.fallbacks:
            response = self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params
            )
        else:
            response = self.client.messages.create(**params)

        if response.stop_reason == "refusal":
            raise TranslationError("claude: richiesta rifiutata dal modello")
        if response.stop_reason == "max_tokens":
            raise TranslationError("claude: risposta troncata (aumenta max_tokens o riduci max_batch_size)")
        text_blocks = [b.text for b in response.content if b.type == "text"]
        if not text_blocks:
            raise TranslationError("claude: risposta senza testo")
        try:
            items = json.loads(text_blocks[-1])["items"]
        except (ValueError, KeyError) as exc:
            raise TranslationError(f"claude: JSON non valido - {text_blocks[-1][:200]!r}") from exc

        by_id = {item["id"]: item for item in items}
        if set(by_id) != set(range(len(texts))):
            raise TranslationError(f"claude: id attesi 0..{len(texts) - 1}, ricevuti {sorted(by_id)}")
        return {t: [by_id[n][t] for n in range(len(texts))] for t in targets}
