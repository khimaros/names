# names

a multilingual names database for exploring human names across languages,
organized by meaning and phonetic similarity.

names lets you research how the same concepts (ocean, light, star, ...)
are expressed as given names in different languages, and discover
sound-alike connections between them.

## features

- store names with original script, romanized form, language, gender, and notes
- group names by semantic meaning (translations derived automatically)
- track phonetic sound-alike links across and within languages
- full-text search across all fields (powered by SQLite FTS5)
- coverage matrix showing which meanings have names in which languages
- suggestion engine for discovering missing links and meaning assignments
- data auditing tools for quality checks
- web UI for browsing and exploration
- compatible with [visidata](https://www.visidata.org/) and
  [datasette](https://datasette.io/) for ad-hoc exploration

## setup

install [uv](https://docs.astral.sh/uv/), then:

```bash
uv sync
```

the CLI has no external dependencies beyond the python standard library.
flask (for the web UI) is installed automatically by `uv sync`.

## usage

### CLI

```bash
# add a meaning and some words
python3 names.py add-meaning "ocean"
python3 names.py add-word "ocean" en -g n -m ocean
python3 names.py add-word "海" ja -r umi -g f -m ocean

# browse
python3 names.py show "ocean:en"
python3 names.py meanings
python3 names.py words -l ja -m ocean

# search
python3 names.py search "ocean"

# bulk import
python3 names.py batch < data.txt

# link sound-alikes
python3 names.py link "海:ja:umi" "mer:fr"

# analysis
python3 names.py coverage
python3 names.py audit
python3 names.py suggest-links --min-score 80
python3 names.py stats
```

set `NAMES_DB` to override the default database path (`names.db`).

see [SKILL.md](SKILL.md) for the full command reference.

### web UI

```bash
uv run python web.py
```

serves a browsable interface on port 5000 with word/meaning detail pages,
language filtering, search, and favorites.

## data model

- **words** have text, romanized form, language code, gender (m/f/n), and notes
- **meanings** are canonical english labels used to group related names
- **translations** are derived automatically from shared meanings
- **sound-alikes** link words with similar pronunciation across languages
- homonyms and multiple readings (e.g. 海/umi vs 海/kai) are separate entries

see [REQUIREMENTS.md](REQUIREMENTS.md) for the full specification and
[DESIGN.md](DESIGN.md) for architecture details.

## license

GPLv3
