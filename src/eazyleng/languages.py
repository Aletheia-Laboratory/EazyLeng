"""Codici lingua (ISO 639-1) e lingue di default."""

#: Lingue di destinazione usate se non ne vengono indicate altre.
DEFAULT_TARGETS = ("en", "fr", "de", "es")

LANGUAGE_NAMES = {
    "ar": "Arabic", "bg": "Bulgarian", "cs": "Czech", "da": "Danish", "de": "German",
    "el": "Greek", "en": "English", "es": "Spanish", "et": "Estonian", "fi": "Finnish",
    "fr": "French", "hr": "Croatian", "hu": "Hungarian", "it": "Italian", "ja": "Japanese",
    "ko": "Korean", "lt": "Lithuanian", "lv": "Latvian", "nl": "Dutch", "no": "Norwegian",
    "pl": "Polish", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian", "sk": "Slovak",
    "sl": "Slovenian", "sq": "Albanian", "sr": "Serbian", "sv": "Swedish", "tr": "Turkish",
    "uk": "Ukrainian", "zh": "Chinese",
}


def normalize(lang: str) -> str:
    """``"EN_us"`` -> ``"en-US"``; ``"IT"`` -> ``"it"``."""
    parts = lang.strip().replace("_", "-").split("-")
    return "-".join([parts[0].lower()] + [p.upper() for p in parts[1:]])


def language_name(lang: str) -> str:
    code = normalize(lang)
    base = LANGUAGE_NAMES.get(code.split("-")[0], code)
    return base if "-" not in code else f"{base} ({code})"
