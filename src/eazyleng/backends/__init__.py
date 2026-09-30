import os

from ..exceptions import ConfigurationError
from .base import HTTPTranslator, Translator
from .claude import ClaudeTranslator
from .deepl import DeepLTranslator
from .google import GoogleTranslator
from .libretranslate import LibreTranslateTranslator
from .static import DictionaryTranslator, FunctionTranslator

BACKENDS = {
    "deepl": DeepLTranslator,
    "google": GoogleTranslator,
    "libretranslate": LibreTranslateTranslator,
    "claude": ClaudeTranslator,
}


# Ordine con cui "auto" cerca le credenziali nell'ambiente.
_AUTO_ENV = (
    ("DEEPL_API_KEY", "deepl"),
    ("ANTHROPIC_API_KEY", "claude"),
    ("GOOGLE_TRANSLATE_API_KEY", "google"),
    ("LIBRETRANSLATE_URL", "libretranslate"),
)


def auto_backend_name() -> str:
    """Nome del primo backend configurato tramite variabili d'ambiente."""
    for env, name in _AUTO_ENV:
        if os.environ.get(env):
            return name
    raise ConfigurationError(
        "Nessun servizio di traduzione configurato: imposta una tra "
        + ", ".join(env for env, _ in _AUTO_ENV)
    )


def get_translator(name: str = "auto", **kwargs) -> Translator:
    """Crea un backend dal nome (``auto``, ``deepl``, ``google``, ``libretranslate``, ``claude``).

    ``auto`` sceglie il servizio in base alla API key presente nell'ambiente.
    """
    if name.lower() == "auto":
        name = auto_backend_name()
    try:
        cls = BACKENDS[name.lower()]
    except KeyError:
        raise ValueError(f"Backend sconosciuto '{name}'. Disponibili: {', '.join(BACKENDS)}") from None
    return cls(**kwargs)


__all__ = [
    "Translator", "HTTPTranslator", "DeepLTranslator", "GoogleTranslator",
    "LibreTranslateTranslator", "ClaudeTranslator", "DictionaryTranslator",
    "FunctionTranslator", "BACKENDS", "get_translator", "auto_backend_name",
]
