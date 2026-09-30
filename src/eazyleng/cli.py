"""Riga di comando.

    eazyleng "Benvenuto nel sito"                       # stampa le traduzioni
    eazyleng "Benvenuto nel sito" --key home.title --db app.db
    eazyleng --nextjs messages                          # messages/it.json -> en.json, fr.json, ...
    eazyleng --file testi.json --backend claude --db app.db
    eazyleng --db app.db --export-nextjs messages       # dal database ai file Next.js
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from typing import Dict, List, Union

from .backends import BACKENDS, get_translator
from .core import EazyLeng
from .exceptions import EazyLengError
from .languages import DEFAULT_TARGETS
from .nextjs import export_store, flatten, translate_messages, write_messages
from .storage import SQLTranslationStore


def _load_items(args) -> Union[Dict[str, str], List[str]]:
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            if args.file.endswith(".json"):
                data = json.load(fh)
                if isinstance(data, dict):
                    return flatten(data)  # accetta anche il formato annidato di Next.js
                if isinstance(data, list):
                    return data
                raise SystemExit("Il file JSON deve contenere un oggetto {chiave: testo} o una lista di testi")
            return [line.rstrip("\n") for line in fh if line.strip()]
    if args.text:
        return {args.key: args.text} if args.key else [args.text]
    text = sys.stdin.read().strip()
    if not text:
        raise SystemExit("Nessun testo da tradurre (passa un testo, --file o usa stdin)")
    return {args.key: text} if args.key else [text]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="eazyleng", description="Traduce testi italiani nelle lingue dell'app.")
    parser.add_argument("text", nargs="?", help="testo italiano da tradurre (altrimenti stdin)")
    parser.add_argument("--key", help="chiave del testo (default: generata dal testo)")
    parser.add_argument("--file", help="file .json ({chiave: testo} o lista) o .txt (un testo per riga)")
    parser.add_argument("--langs", default=",".join(DEFAULT_TARGETS), help="lingue di destinazione separate da virgola")
    parser.add_argument("--source", default="it", help="lingua sorgente (default: it)")
    parser.add_argument("--backend", default="auto", choices=["auto", *sorted(BACKENDS)],
                        help="servizio di traduzione (default: auto, in base alla API key nell'ambiente)")
    parser.add_argument("--context", help="solo claude: contesto/dominio/glossario per la traduzione")
    parser.add_argument("--format", default="json", choices=["json", "rows", "columns", "sql"],
                        help="formato di output (default: json)")
    parser.add_argument("--db", help="salva direttamente in questo database SQLite")
    parser.add_argument("--table", default="translations", help="nome della tabella (default: translations)")
    parser.add_argument("--nextjs", metavar="DIR",
                        help="cartella dei messaggi Next.js: senza testo traduce DIR/it.json nelle altre lingue, "
                             "altrimenti aggiunge i testi tradotti ai file")
    parser.add_argument("--all", action="store_true",
                        help="con --nextjs: ritraduce tutte le chiavi, non solo quelle mancanti")
    parser.add_argument("--export-nextjs", metavar="DIR", help="esporta il database --db in file JSON Next.js")
    args = parser.parse_args(argv)

    if args.export_nextjs:
        if not args.db:
            parser.error("--export-nextjs richiede --db")
        conn = sqlite3.connect(args.db)
        paths = export_store(SQLTranslationStore(conn, table=args.table), args.export_nextjs)
        conn.close()
        print("\n".join(paths))
        return 0

    try:
        kwargs = {"context": args.context} if args.context else {}
        if args.context and args.backend not in ("auto", "claude"):
            parser.error("--context è supportato solo dal backend claude")
        translator = get_translator("claude" if args.context and args.backend == "auto" else args.backend, **kwargs)
        engine = EazyLeng(translator, targets=args.langs.split(","), source=args.source)
        if args.nextjs and not (args.text or args.file):
            records = translate_messages(engine, args.nextjs, only_missing=not args.all)
            print(f"Tradotte {len(records)} chiavi in {args.nextjs}/", file=sys.stderr)
        else:
            records = engine.translate_many(_load_items(args))
            if args.nextjs:
                write_messages(records, args.nextjs)
    except EazyLengError as exc:
        print(f"errore: {exc}", file=sys.stderr)
        return 1

    if args.db:
        conn = sqlite3.connect(args.db)
        store = SQLTranslationStore(conn, table=args.table)
        store.create_table()
        count = store.save(records)
        conn.close()
        print(f"Salvate {count} righe in {args.db}:{args.table}", file=sys.stderr)

    if args.format == "json":
        out = [r.to_dict() for r in records]
        print(json.dumps(out[0] if len(out) == 1 else out, ensure_ascii=False, indent=2))
    elif args.format == "rows":
        print(json.dumps([row for r in records for row in r.to_rows()], ensure_ascii=False, indent=2))
    elif args.format == "columns":
        print(json.dumps([r.to_columns() for r in records], ensure_ascii=False, indent=2))
    else:
        store = SQLTranslationStore(None, table=args.table, dialect="sqlite")
        print(store.create_table_sql() + ";")
        for rec in records:
            for row in rec.to_rows():
                values = ", ".join(_sql_literal(row[c]) for c in ("key", "lang", "text", "is_source", "backend", "updated_at"))
                print(f"INSERT INTO {args.table} (\"key\", \"lang\", \"text\", \"is_source\", \"backend\", \"updated_at\") "
                      f"VALUES ({values});")
    return 0


def _sql_literal(value) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return "'" + str(value).replace("'", "''") + "'"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
