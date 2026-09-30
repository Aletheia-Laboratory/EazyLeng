"""EazyLeng: da un testo italiano a tutte le lingue dell'app, pronto per il DB.

Uso minimo (il servizio viene scelto dalla API key nell'ambiente)::

    from eazyleng import traduci

    traduci("Benvenuto, {nome}!")
    # {"it": "Benvenuto, {nome}!", "en": "Welcome, {nome}!", "fr": ..., ...}

Uso completo::

    from eazyleng import EazyLeng

    tr = EazyLeng(targets=["en", "fr", "de", "es"])
    rec = tr.translate("Benvenuto, {nome}!", key="home.welcome")

    rec.translations   # {"it": "Benvenuto, {nome}!", "en": "Welcome, {nome}!", ...}
    rec.to_rows()      # una riga per lingua -> INSERT
    rec.to_columns()   # {"key": ..., "text_it": ..., "text_en": ...}
    rec.to_json()      # per una colonna JSON
"""

from .backends import (
    ClaudeTranslator,
    DeepLTranslator,
    DictionaryTranslator,
    FunctionTranslator,
    GoogleTranslator,
    LibreTranslateTranslator,
    Translator,
    get_translator,
)
from .core import EazyLeng, TranslationRecord, make_key
from .exceptions import ConfigurationError, EazyLengError, PlaceholderError, TranslationError
from .languages import DEFAULT_TARGETS
from .nextjs import translate_messages, write_messages
from .storage import SQLTranslationStore


def traduci(text, langs=DEFAULT_TARGETS, backend=None):
    """Traduce un testo italiano e restituisce ``{lingua: testo}`` (italiano incluso)."""
    return EazyLeng(backend, targets=langs).translate(text).translations


def traduci_nextjs(directory="messages", langs=DEFAULT_TARGETS, backend=None):
    """Legge ``<directory>/it.json`` e crea/completa i file delle altre lingue per Next.js."""
    return translate_messages(EazyLeng(backend, targets=langs), directory)


__version__ = "0.1.0"

__all__ = [
    "traduci", "traduci_nextjs", "translate_messages", "write_messages",
    "EazyLeng", "TranslationRecord", "make_key", "SQLTranslationStore", "DEFAULT_TARGETS",
    "Translator", "DeepLTranslator", "GoogleTranslator", "LibreTranslateTranslator",
    "ClaudeTranslator", "DictionaryTranslator", "FunctionTranslator", "get_translator",
    "EazyLengError", "TranslationError", "PlaceholderError", "ConfigurationError",
]
