# names database CLI

## word specs

many commands take a **word spec** to identify a word:

- `text:lang` — e.g. `ocean:en`, `海:ja`
- `text:lang:romanized` — e.g. `海:ja:kai`, `海:ja:umi` (when same text has multiple readings)

## browsing

```sh
# list all meanings with word counts
python3 names.py meanings

# list words, with optional filters
python3 names.py words
python3 names.py words -l ja              # by language
python3 names.py words -m ocean           # by meaning
python3 names.py words -l ja -m flower    # combined

# full-text search across text, romanized, meanings, and notes
python3 names.py search 'koi'
python3 names.py search 'ocean'

# show a word with all translations, sound-alikes, and meanings
python3 names.py show 'ocean:en'
python3 names.py show '海:ja:kai'
```

## tracing bad sound-alikes

show the BFS tree of sound-alike links to find which direct link
is pulling in unrelated words:

```sh
python3 names.py trace '春:ja:haru'
```

output is an indented tree — direct links at depth 1, transitive at
depth 2+. each indirect entry shows `← parent` so you know which
link brought it in. to fix a bad chain, unlink the direct connection.

## bulk-adding words (preferred method)

use `batch` to add entire concepts at once. pipe a compact text format
to stdin. meanings are auto-created, translations are auto-linked.

```sh
python3 names.py batch <<'EOF'
= star
en star
ja 星 r:hoshi
vi Sao g:f n:common name
el Αστέρα r:Astéra g:f
fr Estelle g:f n:from Latin stella

= willow
en Willow g:f
ja 柳 r:yanagi
vi Liễu g:f n:common name
EOF
```

format:
- `= meaning` starts a block (auto-created if new)
- `lang text r:romanized g:gender n:note` adds a word
- blank lines and `#` comments are ignored
- existing words are skipped; missing meanings are assigned
- all words in a block are auto-linked as translations

preview with `--dry-run`:

```sh
python3 names.py batch --dry-run < additions.txt
```

## coverage — find gaps

show which languages have words for each meaning:

```sh
python3 names.py coverage              # full matrix
python3 names.py coverage -l vi el fr  # focus on specific languages
```

## adding a new concept (manual method)

example: adding "mountain" in english, japanese, and spanish.
translations are automatic — words sharing a meaning are translations.

```sh
# 1. create the meaning (skip if it already exists)
python3 names.py add-meaning "mountain"

# 2. add words, assigning meanings inline with -m
python3 names.py add-word "mountain" en -m mountain
python3 names.py add-word "山" ja -r yama -m mountain
python3 names.py add-word "montaña" es -g f -m mountain

# no explicit translation links needed — shared meaning connects them
```

## adding a name with multiple meanings

example: 美月 mizuki means both "beauty" and "moon".

```sh
python3 names.py add-word "美月" ja -r mizuki -g f -m beauty moon -n "beauty + moon"
```

## adding a sound-alike

example: linking 雪 yuki (snow) with 勇気 yūki (bravery).

```sh
python3 names.py link "雪:ja:yuki" "勇気:ja"
```

## sound-alike criteria

sound-alikes connect words that share similar phonemes or sound
fragments, regardless of meaning or etymology. valid connections include:

- identical or near-identical pronunciation (kai/kai, ho/ho)
- shared opening syllable (Mar/Mars, Sel-/Sel-, Est-/Est-)
- shared phoneme cluster (ren/ren, sen/sen, jin/jīn)
- one-phoneme difference (haru/hasu, aki/ami, bom/bam)
- rhyming or partial overlap (aki/ryáki, atsu/matsu)

etymology does NOT matter — even coincidental phonetic similarity is
a valid sound-alike. the purpose is to surface phonetic connections
that could inspire name choices, not to document linguistic ancestry.

## finding missing links

use `suggest-links` to find potential sound-alike pairs:

```sh
python3 names.py suggest-links              # score >= 85
python3 names.py suggest-links --min-score 70  # more candidates
python3 names.py suggest-links -l ja zh     # specific languages
```

review suggestions and add with `link`:

```sh
python3 names.py link "穂:ja:ho" "호:ko"
```

## finding missing meanings

use `suggest-meanings` to find words that might be missing meaning
assignments based on what their translation peers have:

```sh
python3 names.py suggest-meanings
```

## assigning an additional meaning to an existing word

```sh
python3 names.py assign-meaning "和:ja" peace
```

## adding a word with same text but different reading

when a kanji has multiple readings (e.g. 海 as umi vs kai), add each
as a separate word with `-r` to distinguish:

```sh
python3 names.py add-word "海" ja -r umi -m ocean
python3 names.py add-word "海" ja -r kai -m ocean -n "sino-japanese reading"
```

reference them in links using the three-part spec:

```sh
python3 names.py link "海:ja:kai" "kai:en"
```

## workflow: adding a new name and connecting it

example: adding the name "Sakura" across languages.

```sh
# ensure meanings exist
python3 names.py meanings | grep blossom

# add words
python3 names.py add-word "桜" ja -r sakura -g f -m "cherry blossom" flower -n "iconic name"
python3 names.py add-word "Sakura" en -g f -m "cherry blossom" flower -n "borrowed from japanese"

# verify
python3 names.py show "桜:ja"
```

## languages

the primary languages used in this database:

| code | language   |
|------|------------|
| en   | english    |
| ja   | japanese   |
| vi   | vietnamese |
| el   | greek      |
| fr   | french     |
| de   | german     |
| es   | spanish    |
| la   | latin      |
| ar   | arabic     |
| he   | hebrew     |
| it   | italian    |
| ru   | russian    |
| pt   | portuguese |
| hi   | hindi      |
| ko   | korean     |
| zh   | chinese    |
| arc  | aramaic    |

## removing and editing

```sh
# remove a word (cascades to meaning links and soundalike links)
python3 names.py remove-word "Taylor:en"

# remove a soundalike link
python3 names.py unlink "Θάλεια:el" "Thái:vi"

# edit word fields (text, romanized, language, gender, note)
python3 names.py edit-word "dawn:en" --text "Dawn"
python3 names.py edit-word "和:ja:kazu" --gender m

# remove a meaning from a word
python3 names.py unassign-meaning "鯉:ja" strength
```

## meaning management

```sh
# rename a meaning
python3 names.py rename-meaning "heaven" "sky"

# merge one meaning into another (moves all words, deletes source)
python3 names.py merge-meanings courage bravery

# remove an empty meaning (fails if words still reference it)
python3 names.py remove-meaning "heaven"
```

## statistics

```sh
# database overview
python3 names.py stats

# word counts per language
python3 names.py words --count

# coverage matrix showing only meanings with gaps
python3 names.py coverage --gaps-only
python3 names.py coverage --gaps-only -l en ja vi el fr
```

## auditing and analysis

```sh
# run all health checks (orphan words, empty meanings, missing gender/romanized, isolated words)
python3 names.py audit

# tab-separated dump for piping into other tools
python3 names.py dump                  # all words
python3 names.py dump -l ja zh ko      # filtered by language

# show same-text entries with different readings (e.g. 海 umi vs kai)
python3 names.py homonyms

# show words whose notes mention borrowing, cognates, or derivation
python3 names.py borrowed

# show words whose text appears in multiple languages (e.g. Clara in de/en/es/pt)
python3 names.py shared-text

# list all soundalike links
python3 names.py links
python3 names.py links -l ja           # links involving japanese words
```

## common pitfalls

### ambiguous word specs

when a text+language pair has multiple readings (e.g. 愛 has ai and
mana in japanese, 蓮 has ren and hasu), commands will error with
"ambiguous: multiple words". use the three-part spec to disambiguate:

```sh
# WRONG — ambiguous
python3 names.py link "愛:ja" "爱:zh"

# RIGHT — specify reading
python3 names.py link "愛:ja:ai" "爱:zh"
```

always check with `homonyms` to find multi-reading entries.

### word specs use text, not romanized

the first part of a word spec is the **text** field (original script),
not the romanized form. for arabic/hebrew/CJK words, use the native
script:

```sh
# WRONG — uses romanized form
python3 names.py link "Salām:ar" "Salome:en"

# RIGHT — uses arabic text
python3 names.py link "سلام:ar" "Salome:en"
```

### foreign key cascades require PRAGMA

sqlite foreign key cascades (ON DELETE CASCADE) only work when
`PRAGMA foreign_keys=ON` is set on the connection. the CLI does this
automatically, but direct sqlite3 shell commands do not — orphaned
rows may result if you delete words via raw SQL without the pragma.

### removing duplicate words

when removing a duplicate, first transfer its soundalike links to the
canonical entry, then remove:

```sh
# 1. check what links the duplicate has
python3 names.py show "Kiran:hi"

# 2. recreate each link on the canonical word
python3 names.py link "Kira:en" "किरण:hi"

# 3. remove the duplicate
python3 names.py remove-word "Kiran:hi"
```

### meanings belong in the database, not notes

if a word's note describes a meaning (e.g. "life/destiny"), that
meaning should be a proper entry in the meanings table. notes should
only contain information that can't be expressed as meanings:
etymology, cultural context, disambiguation, alternative spellings.

after assigning meanings, clean up the note to remove the redundant
parts.

### unassigning a word's only meaning

if you unassign a word's only meaning, it becomes an orphan (flagged
by `audit`). always assign a replacement meaning first, or in the same
batch:

```sh
# unassign old, assign new
python3 names.py unassign-meaning "幸田:ja" friendship
python3 names.py assign-meaning "幸田:ja" joy
python3 names.py assign-meaning "幸田:ja" field
```

## external tools

the database also works with:

```sh
datasette names.db    # web UI with faceting and search
vd names.db           # terminal spreadsheet
```

browsable views: `v_words`, `v_translations`, `v_soundalikes`, `v_meaning_clusters`, `words_fts`.
