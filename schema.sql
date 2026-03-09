PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meanings (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    romanized TEXT,
    language TEXT NOT NULL,
    gender TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS word_meanings (
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    meaning_id INTEGER NOT NULL REFERENCES meanings(id) ON DELETE CASCADE,
    PRIMARY KEY (word_id, meaning_id)
);

CREATE TABLE IF NOT EXISTS soundalikes (
    word_id_a INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    word_id_b INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    PRIMARY KEY (word_id_a, word_id_b),
    CHECK (word_id_a < word_id_b)
);

-- indexes for common lookups
CREATE INDEX IF NOT EXISTS idx_words_language ON words(language);
CREATE INDEX IF NOT EXISTS idx_words_text ON words(text);
CREATE INDEX IF NOT EXISTS idx_word_meanings_meaning ON word_meanings(meaning_id);
CREATE INDEX IF NOT EXISTS idx_soundalikes_b ON soundalikes(word_id_b);

-- full-text search (standalone table, synced via triggers)
CREATE VIRTUAL TABLE IF NOT EXISTS words_fts USING fts5(
    text, romanized, language UNINDEXED, gender UNINDEXED, meanings, note
);

-- rebuild a single word's FTS entry
CREATE TRIGGER IF NOT EXISTS words_ai AFTER INSERT ON words BEGIN
    INSERT INTO words_fts(rowid, text, romanized, language, gender, meanings, note)
    VALUES (new.id, new.text, new.romanized, new.language, new.gender, '', new.note);
END;

CREATE TRIGGER IF NOT EXISTS words_ad AFTER DELETE ON words BEGIN
    DELETE FROM words_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS words_au AFTER UPDATE ON words BEGIN
    DELETE FROM words_fts WHERE rowid = old.id;
    INSERT INTO words_fts(rowid, text, romanized, language, gender, meanings, note)
    VALUES (new.id, new.text, new.romanized, new.language, new.gender,
        COALESCE((SELECT GROUP_CONCAT(m.label, ' ')
         FROM word_meanings wm JOIN meanings m ON wm.meaning_id = m.id
         WHERE wm.word_id = new.id), ''), new.note);
END;

-- resync FTS when meaning associations change
CREATE TRIGGER IF NOT EXISTS wm_ai AFTER INSERT ON word_meanings BEGIN
    DELETE FROM words_fts WHERE rowid = new.word_id;
    INSERT INTO words_fts(rowid, text, romanized, language, gender, meanings, note)
    SELECT w.id, w.text, w.romanized, w.language, w.gender,
        COALESCE((SELECT GROUP_CONCAT(m.label, ' ')
         FROM word_meanings wm JOIN meanings m ON wm.meaning_id = m.id
         WHERE wm.word_id = w.id), ''), w.note
    FROM words w WHERE w.id = new.word_id;
END;

CREATE TRIGGER IF NOT EXISTS wm_ad AFTER DELETE ON word_meanings BEGIN
    DELETE FROM words_fts WHERE rowid = old.word_id;
    INSERT INTO words_fts(rowid, text, romanized, language, gender, meanings, note)
    SELECT w.id, w.text, w.romanized, w.language, w.gender,
        COALESCE((SELECT GROUP_CONCAT(m.label, ' ')
         FROM word_meanings wm JOIN meanings m ON wm.meaning_id = m.id
         WHERE wm.word_id = w.id), ''), w.note
    FROM words w WHERE w.id = old.word_id;
END;

-- resync FTS when a meaning label changes
CREATE TRIGGER IF NOT EXISTS meanings_au AFTER UPDATE ON meanings BEGIN
    DELETE FROM words_fts WHERE rowid IN (
        SELECT word_id FROM word_meanings WHERE meaning_id = new.id);
    INSERT INTO words_fts(rowid, text, romanized, language, gender, meanings, note)
    SELECT w.id, w.text, w.romanized, w.language, w.gender,
        COALESCE((SELECT GROUP_CONCAT(m.label, ' ')
         FROM word_meanings wm JOIN meanings m ON wm.meaning_id = m.id
         WHERE wm.word_id = w.id), ''), w.note
    FROM words w
    WHERE w.id IN (SELECT word_id FROM word_meanings WHERE meaning_id = new.id);
END;

-- browsable views for visidata/datasette

-- all words with their meanings
CREATE VIEW IF NOT EXISTS v_words AS
SELECT
    w.id AS word_id,
    w.text,
    w.romanized,
    w.language,
    w.gender,
    GROUP_CONCAT(m.label, ', ') AS meanings,
    w.note
FROM words w
LEFT JOIN word_meanings wm ON w.id = wm.word_id
LEFT JOIN meanings m ON wm.meaning_id = m.id
GROUP BY w.id;

-- translations derived from shared meanings
CREATE VIEW IF NOT EXISTS v_translations AS
SELECT DISTINCT
    wa.id AS word_a_id,
    wa.text AS word_a_text,
    wa.romanized AS word_a_romanized,
    wa.language AS word_a_lang,
    wb.id AS word_b_id,
    wb.text AS word_b_text,
    wb.romanized AS word_b_romanized,
    wb.language AS word_b_lang
FROM word_meanings wma
JOIN word_meanings wmb ON wma.meaning_id = wmb.meaning_id AND wma.word_id < wmb.word_id
JOIN words wa ON wma.word_id = wa.id
JOIN words wb ON wmb.word_id = wb.id;

-- explicit soundalike links
CREATE VIEW IF NOT EXISTS v_soundalikes AS
SELECT
    wa.id AS word_a_id,
    wa.text AS word_a_text,
    wa.romanized AS word_a_romanized,
    wa.language AS word_a_lang,
    wb.id AS word_b_id,
    wb.text AS word_b_text,
    wb.romanized AS word_b_romanized,
    wb.language AS word_b_lang
FROM soundalikes s
JOIN words wa ON s.word_id_a = wa.id
JOIN words wb ON s.word_id_b = wb.id;

-- meaning clusters: all words grouped by meaning and language
CREATE VIEW IF NOT EXISTS v_meaning_clusters AS
SELECT
    m.id AS meaning_id,
    m.label AS meaning,
    w.language,
    w.id AS word_id,
    w.text,
    w.romanized,
    w.gender
FROM meanings m
JOIN word_meanings wm ON m.id = wm.meaning_id
JOIN words w ON wm.word_id = w.id
ORDER BY m.label, w.language, w.text;
