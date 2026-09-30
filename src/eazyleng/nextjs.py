"""Integrazione con Next.js (next-intl, next-i18next e simili).

Next.js di solito legge le traduzioni da un file JSON per lingua, con chiavi
annidate::

    messages/
      it.json   {"home": {"title": "Benvenuto"}}
      en.json   {"home": {"title": "Welcome"}}

In EazyLeng la chiave ``home.title`` corrisponde a ``{"home": {"title": ...}}``.

Flusso tipico: scrivi (o aggiorni) ``messages/it.json`` e lanci::

    eazyleng --nextjs messages --langs en,fr,de,es

per generare o completare gli altri file di lingua.
"""

from __future__ import annotations

import json
import os
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from .core import EazyLeng, TranslationRecord
from .exceptions import EazyLengError


def flatten(messages: Mapping[str, object], prefix: str = "") -> Dict[str, str]:
    """``{"home": {"title": "Ciao"}}`` -> ``{"home.title": "Ciao"}``."""
    flat: Dict[str, str] = {}
    for key, value in messages.items():
        full = f"{prefix}{key}"
        if isinstance(value, Mapping):
            flat.update(flatten(value, full + "."))
        elif isinstance(value, str):
            flat[full] = value
        else:
            raise EazyLengError(f"Valore non testuale per la chiave '{full}': {value!r}")
    return flat


def unflatten(flat: Mapping[str, str], into: Optional[dict] = None) -> dict:
    """``{"home.title": "Ciao"}`` -> ``{"home": {"title": "Ciao"}}``."""
    tree: dict = into if into is not None else {}
    for key, value in flat.items():
        node = tree
        parts = key.split(".")
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise EazyLengError(f"Conflitto di chiavi: '{part}' è sia un testo sia un gruppo (in '{key}')")
            node = child
        if isinstance(node.get(parts[-1]), dict):
            raise EazyLengError(f"Conflitto di chiavi: '{key}' è già un gruppo di testi")
        node[parts[-1]] = value
    return tree


def to_messages(records: Iterable[TranslationRecord]) -> Dict[str, dict]:
    """Converte i record in ``{lingua: messaggi_annidati}``, il formato di next-intl."""
    per_lang: Dict[str, Dict[str, str]] = {}
    for rec in records:
        for lang, text in rec.translations.items():
            per_lang.setdefault(lang, {})[rec.key] = text
    return {lang: unflatten(flat) for lang, flat in per_lang.items()}


def read_messages(directory: str, lang: str) -> dict:
    path = os.path.join(directory, f"{lang}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_messages(records: Iterable[TranslationRecord], directory: str, *,
                   merge: bool = True, overwrite: bool = True) -> List[str]:
    """Scrive ``<directory>/<lingua>.json`` per ogni lingua dei record.

    Con ``merge=True`` le chiavi già presenti nei file e non toccate dai
    record vengono conservate. Con ``overwrite=False`` le traduzioni già
    presenti (magari corrette a mano) non vengono sostituite.
    Restituisce i percorsi scritti.
    """
    os.makedirs(directory, exist_ok=True)
    per_lang: Dict[str, Dict[str, str]] = {}
    for rec in records:
        for lang, text in rec.translations.items():
            per_lang.setdefault(lang, {})[rec.key] = text

    written = []
    for lang, flat in per_lang.items():
        existing = flatten(read_messages(directory, lang)) if merge else {}
        if not overwrite:
            flat = {k: v for k, v in flat.items() if k not in existing}
        existing.update(flat)
        path = os.path.join(directory, f"{lang}.json")
        _write_json(path, unflatten(existing))
        written.append(path)
    return written


def translate_messages(engine: EazyLeng, directory: str, *, only_missing: bool = True,
                       targets: Optional[Sequence[str]] = None) -> List[TranslationRecord]:
    """Legge ``<directory>/<sorgente>.json`` e genera/aggiorna i file delle altre lingue.

    Con ``only_missing=True`` traduce solo le chiavi assenti in almeno una
    lingua e non sovrascrive le traduzioni esistenti: si può rilanciare a ogni
    modifica di ``it.json`` senza perdere le correzioni manuali.
    """
    source = flatten(read_messages(directory, engine.source))
    if not source:
        raise EazyLengError(f"Nessun messaggio in {os.path.join(directory, engine.source + '.json')}")
    langs = engine.resolve_targets(targets)

    if only_missing:
        existing = {lang: flatten(read_messages(directory, lang)) for lang in langs}
        todo = {k: v for k, v in source.items() if any(k not in existing[lang] for lang in langs)}
    else:
        todo = source

    records = engine.translate_many(todo, targets=langs) if todo else []
    write_messages(records, directory, overwrite=not only_missing)
    return records


def export_store(store, directory: str, langs: Optional[Sequence[str]] = None) -> List[str]:
    """Esporta il contenuto di uno :class:`~eazyleng.storage.SQLTranslationStore` in file Next.js."""
    os.makedirs(directory, exist_ok=True)
    written = []
    for lang in langs or store.languages():
        path = os.path.join(directory, f"{lang}.json")
        _write_json(path, unflatten(store.get_language(lang)))
        written.append(path)
    return written


def _write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
