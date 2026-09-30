# EazyLeng

Scrivi il testo **in italiano**, EazyLeng lo traduce in tutte le lingue del sito
ed è subito pronto per **Next.js** o per il **database**.

- Non tocca placeholder e tag: `{nome}`, `%s`, `<b>…</b>`, plurali ICU `{n, plural, …}`
- Traduce solo le chiavi nuove e non sovrascrive le correzioni fatte a mano
- Servizi: DeepL, Claude, Google Translate, LibreTranslate

---

## 1. Installazione (2 minuti)

```bash
pip install git+https://github.com/Aletheia-Laboratory/EazyLeng.git
```

Imposta **una** chiave (EazyLeng sceglie da solo il servizio):

```bash
export DEEPL_API_KEY="la-tua-chiave"        # consigliato (piano gratuito disponibile)
# oppure: export ANTHROPIC_API_KEY=...      (poi: pip install "eazyleng[claude] @ git+https://github.com/Aletheia-Laboratory/EazyLeng.git")
# oppure: export GOOGLE_TRANSLATE_API_KEY=...
# oppure: export LIBRETRANSLATE_URL=http://localhost:5000
```

---

## 2. Con Next.js (un solo comando)

Scrivi i testi solo in `messages/it.json`:

```json
{
  "home": {
    "title": "Benvenuto, {nome}!",
    "cart": "Hai {count, plural, =0 {il carrello vuoto} one {# prodotto} other {# prodotti}}"
  }
}
```

Lancia:

```bash
eazyleng --nextjs messages
```

Ottieni `messages/en.json`, `fr.json`, `de.json`, `es.json`, già pronti:

```json
{
  "home": {
    "title": "Welcome, {nome}!",
    "cart": "You have {count, plural, =0 {an empty cart} one {# product} other {# products}}"
  }
}
```

Ogni volta che aggiungi testi a `it.json` rilancia lo stesso comando: traduce **solo le chiavi
nuove**. Altre lingue: `--langs en,fr,de,es,pt,ja`.

> Suggerimento: aggiungilo agli script del `package.json`
> ```json
> "scripts": { "i18n": "eazyleng --nextjs messages --langs en,fr,de,es" }
> ```
> e poi `npm run i18n`.

### Configurazione minima di Next.js (App Router + [next-intl](https://next-intl.dev))

```bash
npm install next-intl
```

`i18n/request.ts`
```ts
import { getRequestConfig } from "next-intl/server";

export default getRequestConfig(async ({ requestLocale }) => {
  const locale = (await requestLocale) ?? "it";
  return { locale, messages: (await import(`../messages/${locale}.json`)).default };
});
```

`next.config.ts`
```ts
import createNextIntlPlugin from "next-intl/plugin";
export default createNextIntlPlugin()({});
```

Nei componenti:
```tsx
import { useTranslations } from "next-intl";

export default function Home() {
  const t = useTranslations("home");
  return <h1>{t("title", { nome: "Mario" })}</h1>;
}
```

Per il cambio lingua con URL (`/en`, `/fr`, …) segui la guida
[routing di next-intl](https://next-intl.dev/docs/routing).

---

## 3. Da Python

```python
from eazyleng import traduci

traduci("Benvenuto, {nome}!")
# {"it": "Benvenuto, {nome}!", "en": "Welcome, {nome}!", "fr": "Bienvenue, {nome} !", ...}
```

Scegli le lingue o il servizio:

```python
traduci("Aggiungi al carrello", langs=["en", "de"], backend="claude")
```

Next.js da Python:

```python
from eazyleng import traduci_nextjs
traduci_nextjs("messages", langs=["en", "fr", "de", "es"])
```

---

## 4. Salvare nel database

Da riga di comando (SQLite):

```bash
eazyleng "Benvenuto nel sito" --key home.title --db app.db
```

Da Python, con qualsiasi database (SQLite, PostgreSQL, MySQL):

```python
import sqlite3                     # oppure psycopg / pymysql
from eazyleng import EazyLeng, SQLTranslationStore

tr = EazyLeng(targets=["en", "fr", "de", "es"])
store = SQLTranslationStore(sqlite3.connect("app.db"))
store.create_table()               # una volta sola

store.save(tr.translate_many({
    "home.title": "Benvenuto nel sito",
    "btn.save":   "Salva",
}))

store.get("home.title", "en")      # "Welcome to the site"
store.get_language("fr")           # {"home.title": "...", "btn.save": "..."}
```

Tabella creata (una riga per lingua, aggiungere lingue non cambia lo schema):

| key        | lang | text                | is_source |
|------------|------|---------------------|-----------|
| home.title | it   | Benvenuto nel sito  | true      |
| home.title | en   | Welcome to the site | false     |

Hai già una tua tabella? Prendi i dati nel formato che ti serve:

```python
rec = tr.translate("Salva", key="btn.save")
rec.to_rows()      # [{"key": "btn.save", "lang": "it", "text": "Salva", ...}, ...]  -> una riga per lingua
rec.to_columns()   # {"key": "btn.save", "text_it": "Salva", "text_en": "Save", ...} -> una colonna per lingua
rec.to_json()      # '{"it": "Salva", "en": "Save", ...}'                          -> colonna JSON
```

Dal database ai file Next.js:

```bash
eazyleng --db app.db --export-nextjs messages
```

---

## Comandi utili

| Comando | Cosa fa |
|---|---|
| `eazyleng "Ciao"` | stampa le traduzioni in JSON |
| `eazyleng --nextjs messages` | `it.json` → tutte le altre lingue (solo chiavi nuove) |
| `eazyleng --nextjs messages --all` | ritraduce tutto |
| `eazyleng --file testi.json --db app.db` | traduce un file e salva nel DB |
| `eazyleng "Ciao" --format sql` | genera le `INSERT` SQL |
| `eazyleng --backend claude --context "negozio di abbigliamento" --nextjs messages` | traduzione con contesto (Claude) |

Lingue di default: `en, fr, de, es`. Sorgente: `it` (cambiabile con `--source`).

---

## Sviluppo

```bash
pip install -e ".[dev]"
pytest
```
