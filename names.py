#!/usr/bin/env python3
"""CLI for managing the names database."""

import argparse
import os
import sqlite3
import sys
import unicodedata

DB_PATH = os.environ.get("NAMES_DB", "names.db")


def connect():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys=ON")
    db.row_factory = sqlite3.Row
    return db


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


# ── lookups ────────────────────────────────────────────────────────────

def find_meaning(db, label):
    row = db.execute("SELECT id FROM meanings WHERE label = ?", (label,)).fetchone()
    return row["id"] if row else None


def find_word(db, text, language, romanized=None):
    """find a word by text+language, optionally narrowed by romanized."""
    if romanized:
        row = db.execute(
            "SELECT id FROM words WHERE text = ? AND language = ? AND romanized = ?",
            (text, language, romanized),
        ).fetchone()
    else:
        rows = db.execute(
            "SELECT id FROM words WHERE text = ? AND language = ?",
            (text, language),
        ).fetchall()
        if len(rows) > 1:
            die(f"ambiguous: multiple words '{text}' in '{language}', specify --romanized")
        row = rows[0] if rows else None
    return row["id"] if row else None


def resolve_word(db, spec):
    """resolve a word spec like 'text:lang' or 'text:lang:romanized'."""
    parts = spec.split(":")
    if len(parts) == 2:
        return find_word(db, parts[0], parts[1])
    elif len(parts) == 3:
        return find_word(db, parts[0], parts[1], parts[2])
    else:
        die(f"bad word spec '{spec}', use 'text:lang' or 'text:lang:romanized'")


# ── commands ───────────────────────────────────────────────────────────

def cmd_meanings(args):
    """list all meanings."""
    db = connect()
    query = "SELECT m.id, m.label, COUNT(wm.word_id) AS words FROM meanings m LEFT JOIN word_meanings wm ON m.id = wm.meaning_id GROUP BY m.id ORDER BY m.label"
    for row in db.execute(query):
        print(f"  {row['label']:20s} [{row['words']} words]")


def cmd_words(args):
    """list words, optionally filtered."""
    db = connect()
    clauses, params = [], []
    if args.language:
        placeholders = ",".join("?" * len(args.language))
        clauses.append(f"w.language IN ({placeholders})")
        params.extend(args.language)
    if args.meaning:
        placeholders = ",".join("?" * len(args.meaning))
        clauses.append(f"""EXISTS (SELECT 1 FROM word_meanings wm
            JOIN meanings m ON wm.meaning_id = m.id
            WHERE wm.word_id = w.id AND m.label IN ({placeholders}))""")
        params.extend(args.meaning)
    if args.gender:
        parts = []
        for g in args.gender:
            if g == "n":
                parts.append("w.gender = 'n' OR w.gender IS NULL")
            else:
                parts.append(f"w.gender = '{g}'")
        clauses.append(f"({' OR '.join(parts)})")
    if args.search:
        clauses.append("w.id IN (SELECT rowid FROM words_fts WHERE words_fts MATCH ?)")
        params.append(args.search)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    query = f"""
        SELECT w.id, w.text, w.romanized, w.language, w.gender, w.note,
            GROUP_CONCAT(m.label, ', ') AS meanings
        FROM words w
        LEFT JOIN word_meanings wm ON w.id = wm.word_id
        LEFT JOIN meanings m ON wm.meaning_id = m.id
        {where}
        GROUP BY w.id
        ORDER BY w.language, w.text
    """
    if getattr(args, "count", False):
        count_query = f"""
            SELECT w.language, COUNT(*) AS cnt FROM words w
            {where} GROUP BY w.language ORDER BY w.language
        """
        for row in db.execute(count_query, params):
            print(f"  {row['language']:5s} {row['cnt']}")
        return
    for row in db.execute(query, params):
        rom = f" ({row['romanized']})" if row["romanized"] else ""
        gen = f" [{row['gender']}]" if row["gender"] else ""
        meanings = row["meanings"] or ""
        note = f"  -- {row['note']}" if row["note"] else ""
        print(f"  {row['text']}{rom} [{row['language']}]{gen}  {meanings}{note}")


def cmd_add_meaning(args):
    """add a new meaning."""
    db = connect()
    if find_meaning(db, args.label):
        die(f"meaning '{args.label}' already exists")
    db.execute("INSERT INTO meanings (label) VALUES (?)", (args.label,))
    db.commit()
    print(f"added meaning: {args.label}")


def cmd_add_word(args):
    """add a new word and optionally assign meanings."""
    db = connect()
    existing = find_word(db, args.text, args.language, args.romanized)
    if existing:
        die(f"word '{args.text}' in '{args.language}' already exists (id={existing})")
    cur = db.execute(
        "INSERT INTO words (text, romanized, language, gender, note) VALUES (?, ?, ?, ?, ?)",
        (args.text, args.romanized, args.language, args.gender, args.note),
    )
    word_id = cur.lastrowid
    if args.meanings:
        for label in args.meanings:
            mid = find_meaning(db, label)
            if not mid:
                die(f"meaning '{label}' not found")
            db.execute("INSERT INTO word_meanings (word_id, meaning_id) VALUES (?, ?)", (word_id, mid))
    db.commit()
    meanings_str = ", ".join(args.meanings) if args.meanings else "none"
    print(f"added word: {args.text} [{args.language}] (id={word_id}, meanings: {meanings_str})")


def cmd_add_meaning_to_word(args):
    """assign a meaning to an existing word."""
    db = connect()
    word_id = resolve_word(db, args.word)
    if not word_id:
        die(f"word not found: {args.word}")
    mid = find_meaning(db, args.meaning)
    if not mid:
        die(f"meaning '{args.meaning}' not found")
    try:
        db.execute("INSERT INTO word_meanings (word_id, meaning_id) VALUES (?, ?)", (word_id, mid))
    except sqlite3.IntegrityError:
        die(f"word already has meaning '{args.meaning}'")
    db.commit()
    print(f"assigned meaning '{args.meaning}' to word {args.word}")


def cmd_link(args):
    """create a soundalike link between two words."""
    db = connect()
    id_a = resolve_word(db, args.word_a)
    id_b = resolve_word(db, args.word_b)
    if not id_a:
        die(f"word not found: {args.word_a}")
    if not id_b:
        die(f"word not found: {args.word_b}")
    if id_a > id_b:
        id_a, id_b = id_b, id_a
    try:
        db.execute("INSERT INTO soundalikes (word_id_a, word_id_b) VALUES (?, ?)", (id_a, id_b))
    except sqlite3.IntegrityError:
        die(f"link already exists")
    db.commit()
    print(f"linked {args.word_a} ↔ {args.word_b} (soundalike)")


def print_word_list(rows):
    """print grouped word rows under language headers."""
    current_lang = None
    for r in rows:
        if r["language"] != current_lang:
            current_lang = r["language"]
            print(f"  {current_lang}:")
        rom = f" ({r['romanized']})" if r["romanized"] else ""
        gen = f" [{r['gender']}]" if r["gender"] else ""
        meanings = f"  — {r['meanings']}" if r["meanings"] else ""
        print(f"    {r['text']}{rom}{gen}{meanings}")


def cmd_show(args):
    """show a word with translations (via shared meanings) and soundalikes."""
    db = connect()
    word_id = resolve_word(db, args.word)
    if not word_id:
        die(f"word not found: {args.word}")
    word = db.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
    meanings = db.execute(
        "SELECT m.label FROM word_meanings wm JOIN meanings m ON wm.meaning_id = m.id WHERE wm.word_id = ?",
        (word_id,),
    ).fetchall()

    rom = f" ({word['romanized']})" if word["romanized"] else ""
    gen = f" [{word['gender']}]" if word["gender"] else ""
    note = f"\nnote: {word['note']}" if word["note"] else ""
    meaning_str = ", ".join(r["label"] for r in meanings) if meanings else "none"
    print(f"{word['text']}{rom} — {word['language']}{gen}")
    print(f"meanings: {meaning_str}{note}")

    # soundalikes (transitive — walk the full connected component)
    soundalikes = db.execute("""
        WITH RECURSIVE connected(wid) AS (
            SELECT word_id_b FROM soundalikes WHERE word_id_a = ?
            UNION
            SELECT word_id_a FROM soundalikes WHERE word_id_b = ?
            UNION
            SELECT CASE WHEN s.word_id_a = c.wid THEN s.word_id_b ELSE s.word_id_a END
            FROM soundalikes s JOIN connected c ON s.word_id_a = c.wid OR s.word_id_b = c.wid
        )
        SELECT w.text, w.romanized, w.language, w.gender,
            GROUP_CONCAT(m.label, ', ') AS meanings
        FROM connected r
        JOIN words w ON w.id = r.wid
        LEFT JOIN word_meanings wm ON w.id = wm.word_id
        LEFT JOIN meanings m ON wm.meaning_id = m.id
        WHERE r.wid != ?
        GROUP BY w.id
        ORDER BY w.language, w.text
    """, (word_id, word_id, word_id)).fetchall()
    if soundalikes:
        print(f"\n── sound-alikes {'─' * 25}")
        print_word_list(soundalikes)

    # translations: other words sharing any meaning
    translations = db.execute("""
        SELECT w.text, w.romanized, w.language, w.gender,
            GROUP_CONCAT(m.label, ', ') AS meanings
        FROM (
            SELECT DISTINCT wm.word_id AS wid
            FROM word_meanings wm
            JOIN word_meanings wm2 ON wm.meaning_id = wm2.meaning_id
            WHERE wm2.word_id = ? AND wm.word_id != ?
        ) t
        JOIN words w ON w.id = t.wid
        LEFT JOIN word_meanings wma ON w.id = wma.word_id
        LEFT JOIN meanings m ON wma.meaning_id = m.id
        GROUP BY w.id
        ORDER BY w.language, w.text
    """, (word_id, word_id)).fetchall()
    if translations:
        print(f"\n── translations {'─' * 25}")
        print_word_list(translations)


def cmd_trace(args):
    """show BFS tree of sound-alike links to help find bad connections."""
    db = connect()
    word_id = resolve_word(db, args.word)
    if not word_id:
        die(f"word not found: {args.word}")
    word = db.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
    rom = f" ({word['romanized']})" if word["romanized"] else ""
    print(f"sound-alike trace for {word['text']}{rom} [{word['language']}]:")

    # BFS with parent tracking
    visited = {word_id: None}
    queue = [word_id]
    order = []
    while queue:
        current = queue.pop(0)
        neighbors = db.execute("""
            SELECT CASE WHEN word_id_a = ? THEN word_id_b ELSE word_id_a END AS neighbor
            FROM soundalikes WHERE word_id_a = ? OR word_id_b = ?
        """, (current, current, current)).fetchall()
        for row in neighbors:
            nid = row["neighbor"]
            if nid not in visited:
                visited[nid] = current
                queue.append(nid)
                order.append(nid)

    if not order:
        print("no sound-alikes")
        return

    # compute depths
    def depth(wid):
        d = 0
        while visited[wid] is not None:
            d += 1
            wid = visited[wid]
        return d

    # cache word info
    ids = ",".join(str(i) for i in order)
    rows = db.execute(f"""
        SELECT w.id, w.text, w.romanized, w.language,
            GROUP_CONCAT(m.label, ', ') AS meanings
        FROM words w
        LEFT JOIN word_meanings wm ON w.id = wm.word_id
        LEFT JOIN meanings m ON wm.meaning_id = m.id
        WHERE w.id IN ({ids})
        GROUP BY w.id
    """).fetchall()
    info = {r["id"]: r for r in rows}

    def fmt(wid):
        w = info[wid]
        rom = f" ({w['romanized']})" if w["romanized"] else ""
        meanings = f"  — {w['meanings']}" if w["meanings"] else ""
        return f"{w['text']}{rom} [{w['language']}]{meanings}"

    for wid in order:
        d = depth(wid)
        indent = "  " * d
        parent = visited[wid]
        via = ""
        if parent != word_id:
            p = info[parent]
            p_rom = f" ({p['romanized']})" if p["romanized"] else ""
            via = f"  ← {p['text']}{p_rom}"
        print(f"{indent}{fmt(wid)}{via}")


def cmd_search(args):
    """full-text search across words."""
    db = connect()
    rows = db.execute(
        "SELECT rowid, text, romanized, language, gender, meanings, note FROM words_fts WHERE words_fts MATCH ?",
        (args.query,),
    ).fetchall()
    if not rows:
        print("no results")
        return
    for r in rows:
        rom = f" ({r['romanized']})" if r["romanized"] else ""
        gen = f" [{r['gender']}]" if r["gender"] else ""
        meanings = f"  {r['meanings']}" if r["meanings"] else ""
        note = f"  -- {r['note']}" if r["note"] else ""
        print(f"  {r['text']}{rom} [{r['language']}]{gen}{meanings}{note}")


# ── coverage ──────────────────────────────────────────────────────────

LANG_ORDER = ["en", "ja", "vi", "el", "fr", "es", "de", "la", "ar", "he", "it", "ru", "pt", "hi", "ko", "zh", "arc"]


def cmd_coverage(args):
    """show language coverage matrix for all meanings."""
    db = connect()
    rows = db.execute("""
        SELECT m.label, w.language, COUNT(*) AS cnt
        FROM meanings m
        JOIN word_meanings wm ON m.id = wm.meaning_id
        JOIN words w ON wm.word_id = w.id
        GROUP BY m.id, w.language
        ORDER BY m.label
    """).fetchall()

    # build matrix: {label: {lang: count}}
    matrix = {}
    all_langs = set()
    for r in rows:
        matrix.setdefault(r["label"], {})[r["language"]] = r["cnt"]
        all_langs.add(r["language"])

    # include meanings with zero words
    for r in db.execute("SELECT label FROM meanings"):
        matrix.setdefault(r["label"], {})

    # determine which languages to show
    if args.language:
        langs = args.language
    else:
        langs = [l for l in LANG_ORDER if l in all_langs]
        langs += sorted(all_langs - set(LANG_ORDER))

    # print header
    hdr = f"  {'meaning':20s}" + "".join(f" {l:>4s}" for l in langs)
    print(hdr)
    print("  " + "─" * (len(hdr) - 2))

    for label in sorted(matrix):
        counts = matrix[label]
        if getattr(args, "gaps_only", False) and all(counts.get(l, 0) for l in langs):
            continue
        cells = []
        for l in langs:
            c = counts.get(l, 0)
            cells.append(f" {c or '·':>4}")
        print(f"  {label:20s}{''.join(cells)}")


# ── batch ─────────────────────────────────────────────────────────────

def parse_batch_line(line):
    """parse a word line like 'ja 星 r:hoshi g:f n:some note here'."""
    parts = line.split()
    if len(parts) < 2:
        return None
    lang = parts[0]
    # find where flags start (first token matching key:value)
    text_parts = []
    flags = {"r": None, "g": None, "n": None}
    i = 1
    while i < len(parts):
        if parts[i][:2] in ("r:", "g:", "n:"):
            break
        text_parts.append(parts[i])
        i += 1
    text = " ".join(text_parts)
    # parse flags — note value may contain spaces, so consume until next flag
    while i < len(parts):
        key = parts[i][:1]
        val_start = parts[i][2:]
        val_parts = [val_start]
        i += 1
        while i < len(parts) and parts[i][:2] not in ("r:", "g:", "n:"):
            val_parts.append(parts[i])
            i += 1
        flags[key] = " ".join(val_parts)
    if not text:
        return None
    return {"text": text, "language": lang, "romanized": flags["r"],
            "gender": flags["g"], "note": flags["n"]}


def cmd_batch(args):
    """bulk-add words from a compact text format on stdin."""
    db = connect()
    data = sys.stdin.read()
    blocks = parse_batch_blocks(data)
    dry = args.dry_run

    for meaning_label, word_lines in blocks:
        # ensure meaning exists
        mid = find_meaning(db, meaning_label)
        if not mid and not dry:
            db.execute("INSERT INTO meanings (label) VALUES (?)", (meaning_label,))
            mid = find_meaning(db, meaning_label)
            print(f"  + meaning: {meaning_label}")
        elif not mid:
            print(f"  + meaning: {meaning_label} (dry run)")

        for wl in word_lines:
            parsed = parse_batch_line(wl)
            if not parsed:
                continue
            existing = find_word(db, parsed["text"], parsed["language"], parsed["romanized"])
            if existing:
                if mid and not dry:
                    try:
                        db.execute("INSERT INTO word_meanings (word_id, meaning_id) VALUES (?, ?)",
                                   (existing, mid))
                        print(f"  ~ assign {meaning_label} -> {parsed['text']} [{parsed['language']}]")
                    except sqlite3.IntegrityError:
                        pass
                rom = f" ({parsed['romanized']})" if parsed["romanized"] else ""
                print(f"  . skip: {parsed['text']}{rom} [{parsed['language']}]")
                continue
            if dry:
                rom = f" ({parsed['romanized']})" if parsed["romanized"] else ""
                print(f"  + word: {parsed['text']}{rom} [{parsed['language']}] (dry run)")
                continue
            cur = db.execute(
                "INSERT INTO words (text, romanized, language, gender, note) VALUES (?, ?, ?, ?, ?)",
                (parsed["text"], parsed["romanized"], parsed["language"],
                 parsed["gender"], parsed["note"]),
            )
            wid = cur.lastrowid
            if mid:
                db.execute("INSERT INTO word_meanings (word_id, meaning_id) VALUES (?, ?)", (wid, mid))
            rom = f" ({parsed['romanized']})" if parsed["romanized"] else ""
            print(f"  + word: {parsed['text']}{rom} [{parsed['language']}]")

    if not dry:
        db.commit()
        print("done.")
    else:
        print("dry run complete, no changes made.")


def parse_batch_blocks(data):
    """parse batch text into list of (meaning_label, [word_lines])."""
    blocks = []
    current_meaning = None
    current_lines = []
    for line in data.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("= "):
            if current_meaning is not None:
                blocks.append((current_meaning, current_lines))
            current_meaning = line[2:].strip()
            current_lines = []
        else:
            if current_meaning is not None:
                current_lines.append(line)
    if current_meaning is not None:
        blocks.append((current_meaning, current_lines))
    return blocks


# ── mutation commands ──────────────────────────────────────────────────

def cmd_remove_word(args):
    """delete a word and its meaning links and soundalike links."""
    db = connect()
    word_id = resolve_word(db, args.word)
    if not word_id:
        die(f"word not found: {args.word}")
    word = db.execute("SELECT text, language FROM words WHERE id = ?", (word_id,)).fetchone()
    db.execute("DELETE FROM words WHERE id = ?", (word_id,))
    db.commit()
    print(f"removed {word['text']} [{word['language']}]")


def cmd_unlink(args):
    """remove a soundalike link between two words."""
    db = connect()
    id_a = resolve_word(db, args.word_a)
    id_b = resolve_word(db, args.word_b)
    if not id_a:
        die(f"word not found: {args.word_a}")
    if not id_b:
        die(f"word not found: {args.word_b}")
    if id_a > id_b:
        id_a, id_b = id_b, id_a
    r = db.execute("DELETE FROM soundalikes WHERE word_id_a = ? AND word_id_b = ?", (id_a, id_b))
    if r.rowcount == 0:
        die("no link between those words")
    db.commit()
    print(f"unlinked {args.word_a} ↔ {args.word_b}")


def cmd_edit_word(args):
    """update fields on an existing word."""
    db = connect()
    word_id = resolve_word(db, args.word)
    if not word_id:
        die(f"word not found: {args.word}")
    sets, params = [], []
    for field in ("text", "romanized", "language", "gender", "note"):
        val = getattr(args, field, None)
        if val is not None:
            sets.append(f"{field} = ?")
            params.append(val)
    if not sets:
        die("no fields to update")
    params.append(word_id)
    db.execute(f"UPDATE words SET {', '.join(sets)} WHERE id = ?", params)
    db.commit()
    print(f"updated {args.word}")


def cmd_rename_meaning(args):
    """rename a meaning label."""
    db = connect()
    mid = find_meaning(db, args.old)
    if not mid:
        die(f"meaning '{args.old}' not found")
    if find_meaning(db, args.new):
        die(f"meaning '{args.new}' already exists")
    db.execute("UPDATE meanings SET label = ? WHERE id = ?", (args.new, mid))
    db.commit()
    print(f"renamed meaning '{args.old}' → '{args.new}'")


def cmd_merge_meanings(args):
    """move all word associations from source to target, then delete source."""
    db = connect()
    src_id = find_meaning(db, args.source)
    tgt_id = find_meaning(db, args.target)
    if not src_id:
        die(f"meaning '{args.source}' not found")
    if not tgt_id:
        die(f"meaning '{args.target}' not found")
    # move associations that don't already exist on target
    db.execute("""
        INSERT OR IGNORE INTO word_meanings (word_id, meaning_id)
        SELECT word_id, ? FROM word_meanings WHERE meaning_id = ?
    """, (tgt_id, src_id))
    db.execute("DELETE FROM word_meanings WHERE meaning_id = ?", (src_id,))
    db.execute("DELETE FROM meanings WHERE id = ?", (src_id,))
    db.commit()
    print(f"merged meaning '{args.source}' → '{args.target}'")


def cmd_remove_meaning(args):
    """delete a meaning (only if no words reference it)."""
    db = connect()
    mid = find_meaning(db, args.label)
    if not mid:
        die(f"meaning '{args.label}' not found")
    count = db.execute(
        "SELECT COUNT(*) AS c FROM word_meanings WHERE meaning_id = ?", (mid,)
    ).fetchone()["c"]
    if count > 0:
        die(f"meaning '{args.label}' still has {count} word(s)")
    db.execute("DELETE FROM meanings WHERE id = ?", (mid,))
    db.commit()
    print(f"removed meaning '{args.label}'")


def cmd_unassign_meaning(args):
    """remove a meaning from a word."""
    db = connect()
    word_id = resolve_word(db, args.word)
    if not word_id:
        die(f"word not found: {args.word}")
    mid = find_meaning(db, args.meaning)
    if not mid:
        die(f"meaning '{args.meaning}' not found")
    r = db.execute(
        "DELETE FROM word_meanings WHERE word_id = ? AND meaning_id = ?",
        (word_id, mid),
    )
    if r.rowcount == 0:
        die(f"word does not have meaning '{args.meaning}'")
    db.commit()
    print(f"unassigned meaning '{args.meaning}' from {args.word}")


def cmd_stats(args):
    """show database statistics."""
    db = connect()
    words = db.execute("SELECT COUNT(*) AS c FROM words").fetchone()["c"]
    meanings = db.execute("SELECT COUNT(*) AS c FROM meanings").fetchone()["c"]
    links = db.execute("SELECT COUNT(*) AS c FROM soundalikes").fetchone()["c"]
    print(f"  words:    {words}")
    print(f"  meanings: {meanings}")
    print(f"  links:    {links}")
    print()
    for row in db.execute(
        "SELECT language, COUNT(*) AS c FROM words GROUP BY language ORDER BY language"
    ):
        print(f"  {row['language']:5s} {row['c']}")


# ── audit commands ────────────────────────────────────────────────────

def cmd_dump(args):
    """tab-separated dump of all words for piping and analysis."""
    db = connect()
    clauses, params = [], []
    if args.language:
        placeholders = ",".join("?" * len(args.language))
        clauses.append(f"w.language IN ({placeholders})")
        params.extend(args.language)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    query = f"""
        SELECT w.text, w.romanized, w.language, w.gender, w.note,
            GROUP_CONCAT(m.label, '|') AS meanings
        FROM words w
        LEFT JOIN word_meanings wm ON w.id = wm.word_id
        LEFT JOIN meanings m ON wm.meaning_id = m.id
        {where}
        GROUP BY w.id
        ORDER BY w.language, w.text
    """
    for row in db.execute(query, params):
        fields = [
            row["text"],
            row["romanized"] or "",
            row["language"],
            row["gender"] or "",
            row["meanings"] or "",
            row["note"] or "",
        ]
        print("\t".join(fields))


def cmd_homonyms(args):
    """show same text+language entries with different readings."""
    db = connect()
    rows = db.execute("""
        SELECT w1.text, w1.romanized, w1.language, w1.gender,
            GROUP_CONCAT(DISTINCT m1.label) AS meanings1,
            w2.romanized AS romanized2, w2.gender AS gender2,
            GROUP_CONCAT(DISTINCT m2.label) AS meanings2
        FROM words w1
        JOIN words w2 ON w1.text = w2.text AND w1.language = w2.language AND w1.id < w2.id
        LEFT JOIN word_meanings wm1 ON w1.id = wm1.word_id
        LEFT JOIN meanings m1 ON wm1.meaning_id = m1.id
        LEFT JOIN word_meanings wm2 ON w2.id = wm2.word_id
        LEFT JOIN meanings m2 ON wm2.meaning_id = m2.id
        GROUP BY w1.id, w2.id
        ORDER BY w1.language, w1.text
    """).fetchall()
    if not rows:
        print("no homonyms found")
        return
    for r in rows:
        rom1 = f" ({r['romanized']})" if r["romanized"] else ""
        rom2 = f" ({r['romanized2']})" if r["romanized2"] else ""
        m1 = r["meanings1"] or "none"
        m2 = r["meanings2"] or "none"
        print(f"  {r['text']}{rom1} [{r['language']}] [{m1}]")
        print(f"  {r['text']}{rom2} [{r['language']}] [{m2}]")
        print()


def cmd_borrowed(args):
    """show words whose notes suggest borrowing from another language."""
    db = connect()
    rows = db.execute("""
        SELECT w.text, w.romanized, w.language, w.gender, w.note,
            GROUP_CONCAT(m.label, ', ') AS meanings
        FROM words w
        LEFT JOIN word_meanings wm ON w.id = wm.word_id
        LEFT JOIN meanings m ON wm.meaning_id = m.id
        WHERE w.note LIKE '%borrowed%'
            OR w.note LIKE '%from %'
            OR w.note LIKE '%form of%'
            OR w.note LIKE '% form%'
            OR w.note LIKE '%variant%'
            OR w.note LIKE '%cognate%'
        GROUP BY w.id
        ORDER BY w.language, w.text
    """).fetchall()
    if not rows:
        print("no borrowed words found")
        return
    for r in rows:
        rom = f" ({r['romanized']})" if r["romanized"] else ""
        meanings = r["meanings"] or ""
        print(f"  {r['text']}{rom} [{r['language']}]  {meanings}")
        print(f"    note: {r['note']}")


def cmd_shared_text(args):
    """show words whose text appears in multiple languages."""
    db = connect()
    rows = db.execute("""
        SELECT w.text, w.romanized, w.language, w.gender, w.note,
            GROUP_CONCAT(m.label, ', ') AS meanings
        FROM words w
        LEFT JOIN word_meanings wm ON w.id = wm.word_id
        LEFT JOIN meanings m ON wm.meaning_id = m.id
        WHERE w.text IN (
            SELECT text FROM words GROUP BY text HAVING COUNT(DISTINCT language) > 1
        )
        GROUP BY w.id
        ORDER BY w.text, w.language
    """).fetchall()
    if not rows:
        print("no shared-text words found")
        return
    current = None
    for r in rows:
        if r["text"] != current:
            if current is not None:
                print()
            current = r["text"]
        rom = f" ({r['romanized']})" if r["romanized"] else ""
        gen = f" [{r['gender']}]" if r["gender"] else ""
        meanings = r["meanings"] or ""
        note = f"  -- {r['note']}" if r["note"] else ""
        print(f"  {r['text']}{rom} [{r['language']}]{gen}  {meanings}{note}")


def cmd_audit(args):
    """run health checks on the database."""
    db = connect()
    issues = 0

    # orphan words (no meanings)
    orphans = db.execute("""
        SELECT w.text, w.romanized, w.language FROM words w
        LEFT JOIN word_meanings wm ON w.id = wm.word_id
        WHERE wm.word_id IS NULL ORDER BY w.language, w.text
    """).fetchall()
    if orphans:
        print(f"── words with no meanings ({len(orphans)}) ──")
        for r in orphans:
            rom = f" ({r['romanized']})" if r["romanized"] else ""
            print(f"  {r['text']}{rom} [{r['language']}]")
        print()
        issues += len(orphans)

    # empty meanings (no words)
    empty = db.execute("""
        SELECT m.label FROM meanings m
        LEFT JOIN word_meanings wm ON m.id = wm.meaning_id
        WHERE wm.meaning_id IS NULL ORDER BY m.label
    """).fetchall()
    if empty:
        print(f"── meanings with no words ({len(empty)}) ──")
        for r in empty:
            print(f"  {r['label']}")
        print()
        issues += len(empty)

    # words missing gender
    no_gender = db.execute("""
        SELECT w.text, w.romanized, w.language FROM words w
        WHERE w.gender IS NULL ORDER BY w.language, w.text
    """).fetchall()
    if no_gender:
        print(f"── words missing gender ({len(no_gender)}) ──")
        for r in no_gender:
            rom = f" ({r['romanized']})" if r["romanized"] else ""
            print(f"  {r['text']}{rom} [{r['language']}]")
        print()
        issues += len(no_gender)

    # non-latin scripts missing romanized
    no_rom = db.execute("""
        SELECT w.text, w.language FROM words w
        WHERE w.romanized IS NULL
            AND w.language IN ('ja', 'zh', 'ko', 'ar', 'he', 'hi', 'el', 'ru', 'arc')
        ORDER BY w.language, w.text
    """).fetchall()
    if no_rom:
        print(f"── non-latin words missing romanized ({len(no_rom)}) ──")
        for r in no_rom:
            print(f"  {r['text']} [{r['language']}]")
        print()
        issues += len(no_rom)

    # isolated words (no soundalike links and only one word in their meaning)
    isolated = db.execute("""
        SELECT w.text, w.romanized, w.language FROM words w
        WHERE w.id NOT IN (
            SELECT word_id_a FROM soundalikes UNION SELECT word_id_b FROM soundalikes
        )
        AND w.id NOT IN (
            SELECT wm.word_id FROM word_meanings wm
            JOIN word_meanings wm2 ON wm.meaning_id = wm2.meaning_id AND wm.word_id != wm2.word_id
        )
        ORDER BY w.language, w.text
    """).fetchall()
    if isolated:
        print(f"── isolated words (no links, no co-translations) ({len(isolated)}) ──")
        for r in isolated:
            rom = f" ({r['romanized']})" if r["romanized"] else ""
            print(f"  {r['text']}{rom} [{r['language']}]")
        print()
        issues += len(isolated)

    if issues == 0:
        print("no issues found")
    else:
        print(f"total issues: {issues}")


MIN_SCORE_DEFAULT = 85


def strip_diacritics(s):
    """remove diacritics and lowercase for phonetic comparison."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").lower()


def strip_vowels(s):
    """consonant skeleton — strip vowels from a normalized string."""
    return "".join(c for c in s if c not in "aeiouāēīōū")


def phonetic_score(a, b, same_lang):
    """score phonetic similarity between two normalized romanized forms."""
    if a == b:
        return 100
    if len(a) > 1 and len(b) > 1 and edit_distance_one(a, b):
        return 95
    if len(a) >= 3 and len(b) >= 3 and strip_vowels(a) == strip_vowels(b):
        return 85
    shared = shared_prefix_len(a, b)
    if shared >= 3:
        return 80
    if same_lang and shared >= 2:
        return 70
    return 0


def edit_distance_one(a, b):
    """check if two strings differ by exactly one character."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    diffs = 0
    si = li = 0
    while si < len(short) and li < len(long):
        if short[si] != long[li]:
            diffs += 1
            if diffs > 1:
                return False
            li += 1
        else:
            si += 1
            li += 1
    return True


def shared_prefix_len(a, b):
    """length of shared prefix between two strings."""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def cmd_suggest_links(args):
    """find potential missing sound-alike links by comparing romanized forms."""
    db = connect()
    min_score = args.min_score

    # load all words with usable romanized forms
    rows = db.execute("""
        SELECT w.id, w.text, w.romanized, w.language FROM words w
    """).fetchall()
    words = []
    for r in rows:
        rom = r["romanized"] or r["text"]
        norm = strip_diacritics(rom)
        if norm:
            words.append((r["id"], r["text"], rom, r["language"], norm))

    lang_filter = set(args.language) if args.language else None

    # load existing links (including transitive within 2 hops)
    linked = set()
    for r in db.execute("SELECT word_id_a, word_id_b FROM soundalikes"):
        linked.add((r["word_id_a"], r["word_id_b"]))
        linked.add((r["word_id_b"], r["word_id_a"]))

    # expand to 2-hop transitive
    neighbors = {}
    for a, b in linked:
        neighbors.setdefault(a, set()).add(b)
    transitive = set()
    for wid, nbrs in neighbors.items():
        for n1 in nbrs:
            for n2 in neighbors.get(n1, set()):
                if n2 != wid:
                    transitive.add((wid, n2))
    linked.update(transitive)

    # score all pairs
    suggestions = []
    for i in range(len(words)):
        for j in range(i + 1, len(words)):
            id_a, text_a, rom_a, lang_a, norm_a = words[i]
            id_b, text_b, rom_b, lang_b, norm_b = words[j]
            if (id_a, id_b) in linked or (id_b, id_a) in linked:
                continue
            if lang_filter and lang_a not in lang_filter and lang_b not in lang_filter:
                continue
            same_lang = lang_a == lang_b
            score = phonetic_score(norm_a, norm_b, same_lang)
            if score >= min_score:
                suggestions.append((score, text_a, rom_a, lang_a, text_b, rom_b, lang_b))

    suggestions.sort(key=lambda x: (-x[0], x[3], x[1]))
    if not suggestions:
        print("no suggestions")
        return
    for score, t1, r1, l1, t2, r2, l2 in suggestions:
        d1 = f" ({r1})" if r1 != t1 else ""
        d2 = f" ({r2})" if r2 != t2 else ""
        print(f"  {score:3d}  {t1}{d1} [{l1}]  ↔  {t2}{d2} [{l2}]")


def cmd_suggest_meanings(args):
    """suggest missing meaning assignments based on translation peers."""
    db = connect()

    # for each word, get its meanings
    word_meanings = {}
    for r in db.execute("SELECT word_id, meaning_id FROM word_meanings"):
        word_meanings.setdefault(r["word_id"], set()).add(r["meaning_id"])

    # for each meaning, get words
    meaning_words = {}
    for wid, mids in word_meanings.items():
        for mid in mids:
            meaning_words.setdefault(mid, set()).add(wid)

    # for each word, find meanings held by peers but not by self
    suggestions = {}
    for wid, mids in word_meanings.items():
        peer_meanings = set()
        for mid in mids:
            for peer in meaning_words.get(mid, set()):
                if peer != wid:
                    peer_meanings.update(word_meanings.get(peer, set()))
        missing = peer_meanings - mids
        if missing:
            suggestions[wid] = missing

    if not suggestions:
        print("no suggestions")
        return

    # load word and meaning info for display
    meaning_labels = {}
    for r in db.execute("SELECT id, label FROM meanings"):
        meaning_labels[r["id"]] = r["label"]
    word_info = {}
    for r in db.execute("SELECT id, text, romanized, language FROM words"):
        word_info[r["id"]] = r

    for wid in sorted(suggestions, key=lambda w: (word_info[w]["language"], word_info[w]["text"])):
        w = word_info[wid]
        rom = f" ({w['romanized']})" if w["romanized"] else ""
        missing = sorted(meaning_labels[m] for m in suggestions[wid])
        print(f"  {w['text']}{rom} [{w['language']}]  ← {', '.join(missing)}")


def cmd_links(args):
    """list all soundalike links, optionally filtered by language."""
    db = connect()
    clauses, params = [], []
    if args.language:
        placeholders = ",".join("?" * len(args.language))
        clauses.append(f"(w1.language IN ({placeholders}) OR w2.language IN ({placeholders}))")
        params.extend(args.language)
        params.extend(args.language)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.execute(f"""
        SELECT w1.text AS t1, w1.romanized AS r1, w1.language AS l1,
               w2.text AS t2, w2.romanized AS r2, w2.language AS l2
        FROM soundalikes s
        JOIN words w1 ON s.word_id_a = w1.id
        JOIN words w2 ON s.word_id_b = w2.id
        {where}
        ORDER BY w1.language, w1.text, w2.language, w2.text
    """, params).fetchall()
    if not rows:
        print("no links found")
        return
    for r in rows:
        r1 = f" ({r['r1']})" if r["r1"] else ""
        r2 = f" ({r['r2']})" if r["r2"] else ""
        print(f"  {r['t1']}{r1} [{r['l1']}]  ↔  {r['t2']}{r2} [{r['l2']}]")


# ── main ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="manage the names database")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("meanings", help="list all meanings")

    wp = sub.add_parser("words", help="list words")
    wp.add_argument("-l", "--language", nargs="+", help="filter by language code(s)")
    wp.add_argument("-m", "--meaning", nargs="+", help="filter by meaning label(s)")
    wp.add_argument("-g", "--gender", nargs="+", choices=["m", "f", "n"], help="filter by gender(s)")
    wp.add_argument("-s", "--search", help="full-text search")
    wp.add_argument("--count", action="store_true", help="show counts per language only")

    amp = sub.add_parser("add-meaning", help="add a new meaning")
    amp.add_argument("label")

    awp = sub.add_parser("add-word", help="add a new word")
    awp.add_argument("text")
    awp.add_argument("language", help="language code (en, ja, vi, el, fr, de, es, la, ...)")
    awp.add_argument("-r", "--romanized")
    awp.add_argument("-g", "--gender", choices=["m", "f", "n"])
    awp.add_argument("-n", "--note")
    awp.add_argument("-m", "--meanings", nargs="+", help="meaning labels to assign")

    amw = sub.add_parser("assign-meaning", help="assign a meaning to an existing word")
    amw.add_argument("word", help="word spec: text:lang or text:lang:romanized")
    amw.add_argument("meaning", help="meaning label")

    lp = sub.add_parser("link", help="link two words as sound-alikes")
    lp.add_argument("word_a", help="word spec: text:lang or text:lang:romanized")
    lp.add_argument("word_b", help="word spec: text:lang or text:lang:romanized")

    sp = sub.add_parser("show", help="show a word with relations")
    sp.add_argument("word", help="word spec: text:lang or text:lang:romanized")

    tp = sub.add_parser("trace", help="trace sound-alike links (BFS tree)")
    tp.add_argument("word", help="word spec: text:lang or text:lang:romanized")

    srp = sub.add_parser("search", help="full-text search")
    srp.add_argument("query")

    cvp = sub.add_parser("coverage", help="show language coverage matrix")
    cvp.add_argument("-l", "--language", nargs="+", help="show only these languages")
    cvp.add_argument("--gaps-only", action="store_true", help="only show meanings with gaps")

    btp = sub.add_parser("batch", help="bulk-add words from stdin")
    btp.add_argument("--dry-run", action="store_true", help="preview without changes")

    rwp = sub.add_parser("remove-word", help="delete a word")
    rwp.add_argument("word", help="word spec")

    ulp = sub.add_parser("unlink", help="remove a soundalike link")
    ulp.add_argument("word_a", help="word spec")
    ulp.add_argument("word_b", help="word spec")

    ewp = sub.add_parser("edit-word", help="update word fields")
    ewp.add_argument("word", help="word spec")
    ewp.add_argument("--text", help="new text")
    ewp.add_argument("--romanized", help="new romanized form")
    ewp.add_argument("--language", help="new language code")
    ewp.add_argument("--gender", choices=["m", "f", "n"], help="new gender")
    ewp.add_argument("--note", help="new note")

    rnp = sub.add_parser("rename-meaning", help="rename a meaning")
    rnp.add_argument("old", help="current label")
    rnp.add_argument("new", help="new label")

    mmp = sub.add_parser("merge-meanings", help="merge source into target")
    mmp.add_argument("source", help="source meaning label")
    mmp.add_argument("target", help="target meaning label")

    rmp = sub.add_parser("remove-meaning", help="delete an empty meaning")
    rmp.add_argument("label", help="meaning label")

    ump = sub.add_parser("unassign-meaning", help="remove a meaning from a word")
    ump.add_argument("word", help="word spec")
    ump.add_argument("meaning", help="meaning label")

    sub.add_parser("stats", help="show database statistics")

    dp = sub.add_parser("dump", help="tab-separated word dump")
    dp.add_argument("-l", "--language", nargs="+", help="filter by language code(s)")

    sub.add_parser("homonyms", help="show same-text entries with different readings")

    sub.add_parser("borrowed", help="show words with borrowing notes")

    sub.add_parser("shared-text", help="show words whose text appears in multiple languages")

    sub.add_parser("audit", help="run database health checks")

    slp = sub.add_parser("suggest-links", help="find potential missing sound-alike links")
    slp.add_argument("--min-score", type=int, default=MIN_SCORE_DEFAULT, help="minimum score (default 85)")
    slp.add_argument("-l", "--language", nargs="+", help="only include these languages")

    sub.add_parser("suggest-meanings", help="suggest missing meaning assignments")

    lkp = sub.add_parser("links", help="list all soundalike links")
    lkp.add_argument("-l", "--language", nargs="+", help="filter by language code(s)")

    args = p.parse_args()
    if not args.command:
        p.print_help()
        sys.exit(1)

    commands = {
        "meanings": cmd_meanings,
        "words": cmd_words,
        "add-meaning": cmd_add_meaning,
        "add-word": cmd_add_word,
        "assign-meaning": cmd_add_meaning_to_word,
        "link": cmd_link,
        "show": cmd_show,
        "trace": cmd_trace,
        "search": cmd_search,
        "coverage": cmd_coverage,
        "batch": cmd_batch,
        "remove-word": cmd_remove_word,
        "unlink": cmd_unlink,
        "edit-word": cmd_edit_word,
        "rename-meaning": cmd_rename_meaning,
        "merge-meanings": cmd_merge_meanings,
        "remove-meaning": cmd_remove_meaning,
        "unassign-meaning": cmd_unassign_meaning,
        "stats": cmd_stats,
        "dump": cmd_dump,
        "homonyms": cmd_homonyms,
        "borrowed": cmd_borrowed,
        "shared-text": cmd_shared_text,
        "audit": cmd_audit,
        "suggest-links": cmd_suggest_links,
        "suggest-meanings": cmd_suggest_meanings,
        "links": cmd_links,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
