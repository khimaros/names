#!/usr/bin/env python3
"""web UI for exploring the names database."""

import sqlite3
from collections import defaultdict
from flask import Flask, g, render_template, request

DB_PATH = "names.db"

app = Flask(__name__)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.execute("PRAGMA foreign_keys=ON")
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db:
        db.close()


# ── helpers ────────────────────────────────────────────────────────────

def word_meanings(db, word_id):
    return db.execute("""
        SELECT m.id, m.label
        FROM word_meanings wm JOIN meanings m ON wm.meaning_id = m.id
        WHERE wm.word_id = ? ORDER BY m.label
    """, (word_id,)).fetchall()


def word_translations(db, word_id):
    """get translations (words sharing any meaning), grouped by language."""
    rows = db.execute("""
        SELECT w.id, w.text, w.romanized, w.language, w.gender, w.note,
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
        GROUP BY w.id ORDER BY w.language, w.text
    """, (word_id, word_id)).fetchall()
    grouped = defaultdict(list)
    for r in rows:
        grouped[r["language"]].append(r)
    return dict(grouped)


def word_soundalikes(db, word_id):
    """get soundalike words (transitive), grouped by language."""
    rows = db.execute("""
        WITH RECURSIVE connected(wid) AS (
            SELECT word_id_b FROM soundalikes WHERE word_id_a = ?
            UNION
            SELECT word_id_a FROM soundalikes WHERE word_id_b = ?
            UNION
            SELECT CASE WHEN s.word_id_a = c.wid THEN s.word_id_b ELSE s.word_id_a END
            FROM soundalikes s JOIN connected c ON s.word_id_a = c.wid OR s.word_id_b = c.wid
        )
        SELECT w.id, w.text, w.romanized, w.language, w.gender, w.note,
            GROUP_CONCAT(m.label, ', ') AS meanings
        FROM connected r
        JOIN words w ON w.id = r.wid
        LEFT JOIN word_meanings wm ON w.id = wm.word_id
        LEFT JOIN meanings m ON wm.meaning_id = m.id
        WHERE r.wid != ?
        GROUP BY w.id ORDER BY w.language, w.text
    """, (word_id, word_id, word_id)).fetchall()
    grouped = defaultdict(list)
    for r in rows:
        grouped[r["language"]].append(r)
    return dict(grouped)


def all_languages(db):
    return [r["language"] for r in db.execute(
        "SELECT DISTINCT language FROM words ORDER BY language"
    )]


# ── routes ─────────────────────────────────────────────────────────────

@app.route("/word/<int:word_id>")
def word_detail(word_id):
    db = get_db()
    word = db.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
    if not word:
        return "not found", 404
    meanings = word_meanings(db, word_id)
    translations = word_translations(db, word_id)
    soundalikes = word_soundalikes(db, word_id)
    return render_template("word.html",
        word=word, meanings=meanings,
        translations=translations, soundalikes=soundalikes)


@app.route("/meaning/<int:meaning_id>")
def meaning_detail(meaning_id):
    db = get_db()
    meaning = db.execute("SELECT * FROM meanings WHERE id = ?", (meaning_id,)).fetchone()
    if not meaning:
        return "not found", 404
    words = db.execute("""
        SELECT w.id, w.text, w.romanized, w.language, w.gender, w.note,
            GROUP_CONCAT(m2.label, ', ') AS all_meanings
        FROM word_meanings wm
        JOIN words w ON wm.word_id = w.id
        LEFT JOIN word_meanings wm2 ON w.id = wm2.word_id
        LEFT JOIN meanings m2 ON wm2.meaning_id = m2.id
        WHERE wm.meaning_id = ?
        GROUP BY w.id ORDER BY w.language, w.text
    """, (meaning_id,)).fetchall()
    grouped = defaultdict(list)
    for w in words:
        grouped[w["language"]].append(w)
    return render_template("meaning.html",
        meaning=meaning, words_by_lang=dict(grouped))


@app.route("/meanings")
def meanings_list():
    db = get_db()
    meanings = db.execute("""
        SELECT m.id, m.label, COUNT(wm.word_id) AS word_count,
            COUNT(DISTINCT w.language) AS lang_count
        FROM meanings m
        LEFT JOIN word_meanings wm ON m.id = wm.meaning_id
        LEFT JOIN words w ON wm.word_id = w.id
        GROUP BY m.id ORDER BY m.label
    """).fetchall()
    return render_template("meanings.html", meanings=meanings)


@app.route("/languages")
def languages_list():
    db = get_db()
    langs = db.execute("""
        SELECT w.language,
            COUNT(DISTINCT w.id) AS word_count,
            COUNT(DISTINCT wm.meaning_id) AS meaning_count
        FROM words w
        LEFT JOIN word_meanings wm ON w.id = wm.word_id
        GROUP BY w.language ORDER BY w.language
    """).fetchall()
    return render_template("languages.html", languages=langs)


@app.route("/")
@app.route("/words")
def words_list():
    db = get_db()
    q = request.args.get("q", "").strip()
    langs = request.args.getlist("lang")
    meanings_filter = request.args.getlist("meaning")
    genders = request.args.getlist("gender")
    fav_only = request.args.get("fav", "")
    clauses, params = [], []
    if q:
        clauses.append("w.id IN (SELECT rowid FROM words_fts WHERE words_fts MATCH ?)")
        params.append(q)
    if langs:
        placeholders = ",".join("?" * len(langs))
        clauses.append(f"w.language IN ({placeholders})")
        params.extend(langs)
    if meanings_filter:
        placeholders = ",".join("?" * len(meanings_filter))
        clauses.append(f"""EXISTS (
            SELECT 1 FROM word_meanings wm
            JOIN meanings m ON wm.meaning_id = m.id
            WHERE wm.word_id = w.id AND m.label IN ({placeholders}))""")
        params.extend(meanings_filter)
    if genders:
        parts = []
        for gv in genders:
            if gv == "unspecified":
                parts.append("w.gender IS NULL")
            else:
                parts.append("w.gender = ?")
                params.append(gv)
        clauses.append(f"({' OR '.join(parts)})")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    words = db.execute(f"""
        SELECT w.id, w.text, w.romanized, w.language, w.gender, w.note,
            GROUP_CONCAT(m.label, ', ') AS meanings
        FROM words w
        LEFT JOIN word_meanings wm ON w.id = wm.word_id
        LEFT JOIN meanings m ON wm.meaning_id = m.id
        {where}
        GROUP BY w.id ORDER BY w.language, w.text
    """, params).fetchall()
    languages = all_languages(db)
    meaning_labels = [r["label"] for r in db.execute(
        "SELECT label FROM meanings ORDER BY label")]
    return render_template("words.html",
        words=words, languages=languages, meaning_labels=meaning_labels,
        langs=langs, meanings_filter=meanings_filter, genders=genders,
        fav_only=fav_only, q=q)


@app.route("/language/<lang>")
def language_detail(lang):
    db = get_db()
    words = db.execute("""
        SELECT w.id, w.text, w.romanized, w.gender, w.note,
            GROUP_CONCAT(m.label, ', ') AS meanings
        FROM words w
        LEFT JOIN word_meanings wm ON w.id = wm.word_id
        LEFT JOIN meanings m ON wm.meaning_id = m.id
        WHERE w.language = ?
        GROUP BY w.id ORDER BY w.text
    """, (lang,)).fetchall()
    by_meaning = defaultdict(list)
    for w in words:
        if w["meanings"]:
            for ml in w["meanings"].split(", "):
                by_meaning[ml].append(w)
        else:
            by_meaning["(unassigned)"].append(w)
    return render_template("language.html",
        lang=lang, words=words, by_meaning=dict(sorted(by_meaning.items())))


@app.route("/favorites")
def favorites_page():
    """favorites are stored client-side; this page fetches by IDs."""
    return render_template("favorites.html")


@app.route("/api/words")
def api_words():
    """return words by IDs (for favorites page)."""
    import json
    ids = request.args.getlist("id", type=int)
    if not ids:
        return json.dumps([])
    placeholders = ",".join("?" * len(ids))
    db = get_db()
    rows = db.execute(f"""
        SELECT w.id, w.text, w.romanized, w.language, w.gender, w.note,
            GROUP_CONCAT(m.label, ', ') AS meanings
        FROM words w
        LEFT JOIN word_meanings wm ON w.id = wm.word_id
        LEFT JOIN meanings m ON wm.meaning_id = m.id
        WHERE w.id IN ({placeholders})
        GROUP BY w.id ORDER BY w.language, w.text
    """, ids).fetchall()
    return json.dumps([dict(r) for r in rows]), 200, {"Content-Type": "application/json"}


if __name__ == "__main__":
    app.run(debug=True, port=5000)
