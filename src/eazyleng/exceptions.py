class EazyLengError(Exception):
    """Errore base della libreria."""


class TranslationError(EazyLengError):
    """Il servizio di traduzione ha restituito un errore o una risposta non valida."""


class PlaceholderError(TranslationError):
    """Un placeholder è stato perso o alterato durante la traduzione."""


class ConfigurationError(EazyLengError):
    """Configurazione mancante o non valida (es. API key assente)."""
