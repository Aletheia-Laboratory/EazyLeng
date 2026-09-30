"""Salvataggio dei record in un database relazionale tramite DB-API 2.0.

Funziona con ``sqlite3`` (libreria standard), ``psycopg``/``psycopg2``
(PostgreSQL) e ``pymysql``/``mysqlclient`` (MySQL/MariaDB). Lo schema è
normalizzato: una riga per coppia (chiave, lingua).

    CREATE TABLE translations (
        key        VARCHAR(255) NOT NULL,
        lang       VARCHAR(16)  NOT NULL,
        text       TEXT         NOT NULL,
        is_source  BOOLEAN      NOT NULL DEFAULT FALSE,
        backend    VARCHAR(32),
        updated_at VARCHAR(32),
        PRIMARY KEY (key, lang)
    );
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Union

from .core import TranslationRecord

_DIALECTS = ("sqlite", "postgres", "mysql")
_COLUMNS = ("key", "lang", "text", "is_source", "backend", "updated_at")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


class SQLTranslationStore:
    """Scrive e legge le traduzioni su una connessione DB-API.

    >>> import sqlite3
    >>> store = SQLTranslationStore(sqlite3.connect("app.db"))
    >>> store.create_table()
    >>> store.save(records)
    >>> store.get("home.welcome", "en")
    """

    def __init__(self, connection, table: str = "translations", dialect: Optional[str] = None):
        if not _IDENT_RE.match(table):
            raise ValueError(f"Nome tabella non valido: {table!r}")
        self.conn = connection
        self.table = table
        self.dialect = dialect or _detect_dialect(connection)
        if self.dialect not in _DIALECTS:
            raise ValueError(f"Dialetto non supportato '{self.dialect}'. Usa uno tra: {', '.join(_DIALECTS)}")
        self._ph = "?" if self.dialect == "sqlite" else "%s"

    def _q(self, name: str) -> str:
        # "key" è parola riservata in MySQL.
        return f"`{name}`" if self.dialect == "mysql" else f'"{name}"'

    # --- DDL ------------------------------------------------------------------------

    def create_table_sql(self) -> str:
        q = self._q
        return (
            f"CREATE TABLE IF NOT EXISTS {self.table} (\n"
            f"    {q('key')} VARCHAR(255) NOT NULL,\n"
            f"    {q('lang')} VARCHAR(16) NOT NULL,\n"
            f"    {q('text')} TEXT NOT NULL,\n"
            f"    {q('is_source')} BOOLEAN NOT NULL DEFAULT FALSE,\n"
            f"    {q('backend')} VARCHAR(32),\n"
            f"    {q('updated_at')} VARCHAR(32),\n"
            f"    PRIMARY KEY ({q('key')}, {q('lang')})\n"
            f")"
        )

    def create_table(self) -> None:
        cur = self.conn.cursor()
        cur.execute(self.create_table_sql())
        self.conn.commit()

    # --- Scrittura --------------------------------------------------------------------

    def upsert_sql(self) -> str:
        q = self._q
        cols = ", ".join(q(c) for c in _COLUMNS)
        values = ", ".join([self._ph] * len(_COLUMNS))
        updates = [c for c in _COLUMNS if c not in ("key", "lang")]
        if self.dialect == "mysql":
            tail = "ON DUPLICATE KEY UPDATE " + ", ".join(f"{q(c)} = VALUES({q(c)})" for c in updates)
        else:
            tail = (f"ON CONFLICT ({q('key')}, {q('lang')}) DO UPDATE SET "
                    + ", ".join(f"{q(c)} = excluded.{q(c)}" for c in updates))
        return f"INSERT INTO {self.table} ({cols}) VALUES ({values}) {tail}"

    def save(self, records: Union[TranslationRecord, Iterable[TranslationRecord]], commit: bool = True) -> int:
        """Inserisce o aggiorna i record; restituisce il numero di righe scritte."""
        if isinstance(records, TranslationRecord):
            records = [records]
        rows = [tuple(row[c] for c in _COLUMNS) for rec in records for row in rec.to_rows()]
        if rows:
            cur = self.conn.cursor()
            cur.executemany(self.upsert_sql(), rows)
            if commit:
                self.conn.commit()
        return len(rows)

    def delete(self, key: str, commit: bool = True) -> None:
        cur = self.conn.cursor()
        cur.execute(f"DELETE FROM {self.table} WHERE {self._q('key')} = {self._ph}", (key,))
        if commit:
            self.conn.commit()

    # --- Lettura -------------------------------------------------------------------------

    def get(self, key: str, lang: str, fallback: Optional[str] = None) -> Optional[str]:
        """Testo di ``key`` in ``lang``; se manca usa ``fallback``, poi la lingua sorgente."""
        translations = self.get_all(key)
        if lang in translations:
            return translations[lang]
        if fallback and fallback in translations:
            return translations[fallback]
        return self._source_text(key)

    def get_all(self, key: str) -> Dict[str, str]:
        q = self._q
        cur = self.conn.cursor()
        cur.execute(f"SELECT {q('lang')}, {q('text')} FROM {self.table} WHERE {q('key')} = {self._ph}", (key,))
        return {lang: text for lang, text in cur.fetchall()}

    def get_language(self, lang: str) -> Dict[str, str]:
        """Tutte le stringhe di una lingua come ``{chiave: testo}`` (utile per il cambio lingua)."""
        q = self._q
        cur = self.conn.cursor()
        cur.execute(f"SELECT {q('key')}, {q('text')} FROM {self.table} WHERE {q('lang')} = {self._ph}", (lang,))
        return dict(cur.fetchall())

    def languages(self) -> List[str]:
        cur = self.conn.cursor()
        cur.execute(f"SELECT DISTINCT {self._q('lang')} FROM {self.table} ORDER BY {self._q('lang')}")
        return [r[0] for r in cur.fetchall()]

    def keys(self) -> List[str]:
        cur = self.conn.cursor()
        cur.execute(f"SELECT DISTINCT {self._q('key')} FROM {self.table} ORDER BY {self._q('key')}")
        return [r[0] for r in cur.fetchall()]

    def _source_text(self, key: str) -> Optional[str]:
        q = self._q
        cur = self.conn.cursor()
        cur.execute(
            f"SELECT {q('text')} FROM {self.table} WHERE {q('key')} = {self._ph} AND {q('is_source')} = {self._ph}",
            (key, True),
        )
        row = cur.fetchone()
        return row[0] if row else None


def _detect_dialect(connection) -> str:
    module = type(connection).__module__.split(".")[0].lower()
    if module in ("sqlite3", "_sqlite3"):
        return "sqlite"
    if module.startswith("psycopg") or module in ("pg8000", "asyncpg"):
        return "postgres"
    if module in ("pymysql", "mysqldb", "mysql", "mariadb", "_mysql"):
        return "mysql"
    raise ValueError(f"Impossibile riconoscere il database dalla connessione ({module}): passa dialect=...")
