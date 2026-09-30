import json
import sqlite3
from types import SimpleNamespace

import pytest

from eazyleng import (
    ClaudeTranslator,
    DeepLTranslator,
    DictionaryTranslator,
    EazyLeng,
    FunctionTranslator,
    PlaceholderError,
    SQLTranslationStore,
    TranslationRecord,
    make_key,
)
from eazyleng.backends.base import Translator
from eazyleng.cli import main
from eazyleng.placeholders import LARAVEL_PATTERN, mask


class FakeTranslator(Translator):
    """Antepone il codice lingua; registra le chiamate."""

    name = "fake"

    def __init__(self, markup=False):
        super().__init__()
        self.markup = markup
        self.calls = []

    def translate_batch(self, texts, source, target):
        self.calls.append((list(texts), source, target))
        return [f"[{target}] {t}" for t in texts]


# --- placeholder ------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("Ciao {nome}", ["{nome}"]),
    ("Hai %(n)d messaggi e %s notifiche", ["%(n)d", "%s"]),
    ("Totale: {prezzo:.2f} €", ["{prezzo:.2f}"]),
    ("Ciao {{ utente.nome }}", ["{{ utente.nome }}"]),
    ('Clicca <a href="/x">qui</a>', ['<a href="/x">', "</a>"]),
    ("Nessun placeholder", []),
])
def test_mask_finds_placeholders(text, expected):
    assert mask(text).placeholders == expected


def test_mask_roundtrip_markup_escapes_text():
    m = mask("Tom & Jerry < {nome}", markup=True)
    assert m.text == 'Tom &amp; Jerry &lt; <x id="0"/>'
    assert m.unmask('Tom &amp; Jerry &lt; <x id="0" />') == "Tom & Jerry < {nome}"


def test_unmask_detects_lost_placeholder():
    m = mask("Ciao {nome}")
    with pytest.raises(PlaceholderError):
        m.unmask("Hello")


def test_laravel_pattern_is_opt_in():
    assert mask("Ciao :nome, ore 10:30").placeholders == []
    assert mask("Ciao :nome, ore 10:30", extra_patterns=[LARAVEL_PATTERN]).placeholders == [":nome"]


# --- core -------------------------------------------------------------------------

def test_translate_single_builds_record():
    tr = EazyLeng(FakeTranslator(), targets=["en", "FR", "it", "en"])
    rec = tr.translate("Benvenuto, {nome}!", key="home.welcome")

    assert rec.key == "home.welcome"
    assert rec.translations == {
        "it": "Benvenuto, {nome}!",
        "en": "[en] Benvenuto, {nome}!",
        "fr": "[fr] Benvenuto, {nome}!",
    }
    assert rec["en"] == "[en] Benvenuto, {nome}!"
    assert rec.get("en-US") == rec["en"]
    assert rec.get("ja") == rec.source_text


def test_placeholders_are_masked_before_sending():
    fake = FakeTranslator()
    EazyLeng(fake, targets=["en"]).translate("Ciao {nome}")
    assert fake.calls[0][0] == ['Ciao <x id="0"/>']


def test_whitespace_and_non_text_are_preserved():
    fake = FakeTranslator()
    tr = EazyLeng(fake, targets=["en"])
    recs = tr.translate_many(["  Ciao\n", "", "123", "{nome}"])
    assert [r["en"] for r in recs] == ["  [en] Ciao\n", "", "123", "{nome}"]
    assert fake.calls == [(["Ciao"], "it", "en")]


def test_translate_many_dedups_and_caches():
    fake = FakeTranslator()
    cache = {}
    tr = EazyLeng(fake, targets=["en", "de"], cache=cache)
    recs = tr.translate_many({"a": "Salva", "b": "Salva", "c": "Annulla"})
    assert [r.key for r in recs] == ["a", "b", "c"]
    assert recs[1]["de"] == "[de] Salva"
    assert len(fake.calls) == 2 and all(call[0] == ["Salva", "Annulla"] for call in fake.calls)

    fake.calls.clear()
    tr.translate("Salva")
    assert fake.calls == []


def test_list_input_generates_stable_keys():
    tr = EazyLeng(FakeTranslator(), targets=["en"], key_prefix="ui.")
    rec = tr.translate_many(["Perché è così?"])[0]
    assert rec.key == make_key("Perché è così?", "ui.")
    assert rec.key.startswith("ui.perche_e_cosi_")


def test_record_formats():
    tr = EazyLeng(FakeTranslator(), targets=["en", "pt-BR"])
    rec = tr.translate("Ciao", key="k")

    rows = rec.to_rows()
    assert [(r["lang"], r["is_source"]) for r in rows] == [("it", True), ("en", False), ("pt-BR", False)]
    assert rec.to_columns() == {"key": "k", "text_it": "Ciao", "text_en": "[en] Ciao", "text_pt_br": "[pt-BR] Ciao"}
    assert json.loads(rec.to_json()) == rec.translations
    assert TranslationRecord.from_dict(rec.to_dict()) == rec


def test_markup_backend_receives_escaped_text():
    fake = FakeTranslator(markup=True)
    rec = EazyLeng(fake, targets=["en"]).translate("Tom & Jerry {x}")
    assert fake.calls[0][0] == ['Tom &amp; Jerry <x id="0"/>']
    assert rec["en"] == "[en] Tom & Jerry {x}"


def test_dictionary_translator_with_fallback():
    dt = DictionaryTranslator({"en": {"Salva": "Save"}}, fallback=FakeTranslator())
    recs = EazyLeng(dt, targets=["en"]).translate_many(["Salva", "Esci"])
    assert [r["en"] for r in recs] == ["Save", "[en] Esci"]


def test_function_translator():
    ft = FunctionTranslator(lambda text, src, tgt: text.upper())
    assert EazyLeng(ft, targets=["en"]).translate("ciao")["en"] == "CIAO"


# --- backend ---------------------------------------------------------------------

def test_deepl_request_shape(monkeypatch):
    dl = DeepLTranslator(api_key="abc:fx")
    sent = {}

    def fake_post(url, *, json_body=None, headers=None, data=None):
        sent.update(url=url, body=json_body, headers=headers)
        return {"translations": [{"text": t.replace("Ciao", "Hello")} for t in json_body["text"]]}

    monkeypatch.setattr(dl, "_post", fake_post)
    rec = EazyLeng(dl, targets=["en"]).translate("Ciao {nome}")
    assert sent["url"] == "https://api-free.deepl.com/v2/translate"
    assert sent["body"]["target_lang"] == "EN-GB" and sent["body"]["source_lang"] == "IT"
    assert sent["headers"]["Authorization"] == "DeepL-Auth-Key abc:fx"
    assert rec["en"] == "Hello {nome}"


class FakeClaudeClient:
    def __init__(self):
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.requests.append(params)
        items = json.loads(params["messages"][0]["content"].split("\n\n", 1)[1])
        langs = params["output_config"]["format"]["schema"]["properties"]["items"]["items"]["required"][1:]
        out = {"items": [{"id": it["id"], **{l: f"<{l}>{it['text']}" for l in langs}} for it in items]}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(out))])


def test_claude_translates_all_languages_in_one_request():
    client = FakeClaudeClient()
    ct = ClaudeTranslator(client=client, context="E-commerce di abbigliamento")
    recs = EazyLeng(ct, targets=["en", "fr", "de"]).translate_many(["Carrello", "Paga {totale}"])

    assert len(client.requests) == 1
    req = client.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["fallbacks"] == "default"
    assert "E-commerce di abbigliamento" in req["system"]
    assert recs[1]["fr"] == "<fr>Paga {totale}"


# --- storage ---------------------------------------------------------------------

def test_sqlite_store_roundtrip():
    conn = sqlite3.connect(":memory:")
    store = SQLTranslationStore(conn)
    store.create_table()

    tr = EazyLeng(FakeTranslator(), targets=["en", "fr"])
    assert store.save(tr.translate_many({"home.title": "Benvenuto", "btn.save": "Salva"})) == 6
    assert store.get("home.title", "en") == "[en] Benvenuto"
    assert store.get("home.title", "ja") == "Benvenuto"
    assert store.get_language("fr") == {"home.title": "[fr] Benvenuto", "btn.save": "[fr] Salva"}
    assert store.keys() == ["btn.save", "home.title"]

    # upsert: la stessa chiave viene aggiornata, non duplicata
    store.save(TranslationRecord("home.title", "it", "Ciao", {"it": "Ciao", "en": "Hi"}))
    assert store.get_all("home.title") == {"it": "Ciao", "en": "Hi", "fr": "[fr] Benvenuto"}


@pytest.mark.parametrize("dialect, fragment", [
    ("postgres", 'ON CONFLICT ("key", "lang") DO UPDATE'),
    ("mysql", "ON DUPLICATE KEY UPDATE `text` = VALUES(`text`)"),
])
def test_upsert_sql_dialects(dialect, fragment):
    sql = SQLTranslationStore(None, dialect=dialect).upsert_sql()
    assert fragment in sql
    assert "%s" in sql


def test_invalid_table_name_rejected():
    with pytest.raises(ValueError):
        SQLTranslationStore(None, table="x; DROP TABLE y", dialect="sqlite")


# --- CLI -------------------------------------------------------------------------

def test_cli_saves_to_sqlite(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("eazyleng.cli.get_translator", lambda name, **kw: FakeTranslator())
    db = tmp_path / "app.db"
    assert main(["Buongiorno", "--key", "greet", "--langs", "en,es", "--db", str(db)]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["translations"]["es"] == "[es] Buongiorno"
    rows = sqlite3.connect(db).execute('SELECT lang, text FROM translations ORDER BY lang').fetchall()
    assert rows == [("en", "[en] Buongiorno"), ("es", "[es] Buongiorno"), ("it", "Buongiorno")]


def test_cli_sql_output_escapes_quotes(monkeypatch, capsys):
    monkeypatch.setattr("eazyleng.cli.get_translator", lambda name, **kw: FakeTranslator())
    assert main(["L'ora", "--key", "k", "--langs", "en", "--format", "sql"]) == 0
    assert "'[en] L''ora'" in capsys.readouterr().out


# --- ICU / Next.js ---------------------------------------------------------------

from eazyleng import ConfigurationError, traduci
from eazyleng.nextjs import flatten, to_messages, translate_messages, unflatten, write_messages


def test_icu_plural_structure_is_protected():
    text = "Hai {count, plural, =0 {nessun messaggio} one {# messaggio} other {# messaggi}}"
    m = mask(text)
    assert m.text == 'Hai <x id="0"/>nessun messaggio<x id="1"/> messaggio<x id="2"/> messaggi<x id="3"/>'
    assert m.unmask(m.text) == text


def test_icu_select_with_nested_plural_and_rich_text():
    text = "{g, select, male {Lui} other {Loro}} ha {n, plural, one {un <b>gatto</b>} other {{n} gatti}}"
    m = mask(text, markup=True)
    assert "Lui" in m.text and "gatto" in m.text and "plural" not in m.text and "{n}" not in m.text
    assert m.unmask(m.text) == text


def test_malformed_icu_falls_back_to_simple_placeholders():
    assert mask("Rotto {n, plural, one {x}").placeholders == ["{x}"]


def test_flatten_unflatten():
    nested = {"home": {"title": "Ciao", "cta": {"buy": "Compra"}}, "ok": "Ok"}
    flat = flatten(nested)
    assert flat == {"home.title": "Ciao", "home.cta.buy": "Compra", "ok": "Ok"}
    assert unflatten(flat) == nested


def test_to_messages_groups_by_language():
    recs = EazyLeng(FakeTranslator(), targets=["en"]).translate_many({"home.title": "Ciao"})
    assert to_messages(recs) == {"it": {"home": {"title": "Ciao"}}, "en": {"home": {"title": "[en] Ciao"}}}


def test_translate_messages_only_missing(tmp_path):
    (tmp_path / "it.json").write_text(json.dumps({"home": {"title": "Ciao", "body": "Testo"}}), encoding="utf-8")
    (tmp_path / "en.json").write_text(json.dumps({"home": {"title": "Hello (a mano)"}}), encoding="utf-8")
    fake = FakeTranslator()
    tr = EazyLeng(fake, targets=["en", "fr"])

    translate_messages(tr, str(tmp_path))
    en = json.loads((tmp_path / "en.json").read_text(encoding="utf-8"))
    fr = json.loads((tmp_path / "fr.json").read_text(encoding="utf-8"))
    assert en == {"home": {"title": "Hello (a mano)", "body": "[en] Testo"}}  # correzione manuale conservata
    assert fr == {"home": {"title": "[fr] Ciao", "body": "[fr] Testo"}}

    fake.calls.clear()
    assert translate_messages(tr, str(tmp_path)) == []  # niente da fare al secondo giro
    assert fake.calls == []


def test_write_messages_merges_existing(tmp_path):
    (tmp_path / "en.json").write_text(json.dumps({"old": "Old"}), encoding="utf-8")
    recs = EazyLeng(FakeTranslator(), targets=["en"]).translate_many({"new.key": "Nuovo"})
    write_messages(recs, str(tmp_path))
    assert json.loads((tmp_path / "en.json").read_text(encoding="utf-8")) == {"old": "Old", "new": {"key": "[en] Nuovo"}}


def test_cli_nextjs_and_export(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("eazyleng.cli.get_translator", lambda name, **kw: FakeTranslator())
    msgs = tmp_path / "messages"
    msgs.mkdir()
    (msgs / "it.json").write_text(json.dumps({"nav": {"home": "Pagina iniziale"}}), encoding="utf-8")
    assert main(["--nextjs", str(msgs), "--langs", "en"]) == 0
    assert json.loads((msgs / "en.json").read_text(encoding="utf-8")) == {"nav": {"home": "[en] Pagina iniziale"}}

    db = tmp_path / "app.db"
    assert main(["Esci", "--key", "nav.logout", "--langs", "en", "--db", str(db)]) == 0
    out = tmp_path / "export"
    assert main(["--db", str(db), "--export-nextjs", str(out)]) == 0
    assert json.loads((out / "en.json").read_text(encoding="utf-8")) == {"nav": {"logout": "[en] Esci"}}


def test_auto_backend(monkeypatch):
    for env in ("DEEPL_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_TRANSLATE_API_KEY", "LIBRETRANSLATE_URL"):
        monkeypatch.delenv(env, raising=False)
    with pytest.raises(ConfigurationError):
        EazyLeng()
    monkeypatch.setenv("DEEPL_API_KEY", "k:fx")
    assert isinstance(EazyLeng().translator, DeepLTranslator)


def test_traduci_shortcut(monkeypatch):
    fake = FakeTranslator()
    assert traduci("Ciao", langs=["en"], backend=fake) == {"it": "Ciao", "en": "[en] Ciao"}
