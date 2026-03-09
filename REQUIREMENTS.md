# requirements

## data model

- store words used as human names with: language, original script, romanized
  form, gender, and a freeform note
- separate meanings table with canonical english labels for grouping/faceting
- words can have multiple meanings (many-to-many via word_meanings join table)
- translations are derived from shared meanings (no explicit links needed)
- sound-alike links between words stored in soundalikes table
- same-language sound-alike links are allowed
- homonyms are represented as separate rows disambiguated by meaning and note
- same kanji with different readings are separate word entries
  (e.g. 海/umi and 海/kai are two rows)

## views

- **by name**: select a word, see:
  - all translations (words sharing a meaning) grouped by language
  - all sound-alikes grouped by language with their meanings
  - the word's own meanings
- **by meaning/concept**: select a meaning, see all words sharing that meaning
  grouped by language
- **search**: full-text search across original script, romanized form, and
  notes

## tech

- sqlite database with FTS5 for full-text search
- schema should work out of the box with visidata and datasette
- sql views for concept clusters and browsable exploration
- CLI tool for data entry (add words, link soundalikes, batch import)
