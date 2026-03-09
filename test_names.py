#!/usr/bin/env python3
"""integration tests for names.py batch and coverage commands."""

import os
import sqlite3
import subprocess
import tempfile
import textwrap
import unittest

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
NAMES_PY = os.path.join(os.path.dirname(__file__), "names.py")


def run_cli(*args, stdin=None, db_path=None):
    env = os.environ.copy()
    if db_path:
        env["NAMES_DB"] = db_path
    result = subprocess.run(
        ["python3", NAMES_PY, *args],
        capture_output=True, text=True, input=stdin, env=env,
    )
    return result


def make_db(tmp_dir):
    """create a fresh database from schema, return its path."""
    db_path = os.path.join(tmp_dir, "test.db")
    db = sqlite3.connect(db_path)
    with open(SCHEMA_PATH) as f:
        db.executescript(f.read())
    db.close()
    return db_path


class TestCoverage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        # seed some data
        run_cli("add-meaning", "ocean", db_path=self.db_path)
        run_cli("add-meaning", "forest", db_path=self.db_path)
        run_cli("add-word", "ocean", "en", "-m", "ocean", db_path=self.db_path)
        run_cli("add-word", "海", "ja", "-r", "umi", "-m", "ocean", db_path=self.db_path)
        run_cli("add-word", "forest", "en", "-m", "forest", db_path=self.db_path)

    def test_coverage_shows_all_meanings(self):
        r = run_cli("coverage", db_path=self.db_path)
        self.assertEqual(r.returncode, 0)
        self.assertIn("ocean", r.stdout)
        self.assertIn("forest", r.stdout)

    def test_coverage_shows_language_counts(self):
        r = run_cli("coverage", db_path=self.db_path)
        self.assertEqual(r.returncode, 0)
        lines = r.stdout.strip().split("\n")
        # header should list languages
        header = lines[0]
        self.assertIn("en", header)
        self.assertIn("ja", header)
        # ocean has counts in both en and ja columns
        ocean_line = [l for l in lines if "ocean" in l and "meaning" not in l][0]
        # should have two non-zero values
        self.assertNotIn("·", ocean_line.replace("ocean", "").strip()[:8])

    def test_coverage_filter_by_language(self):
        r = run_cli("coverage", "-l", "vi", "el", "fr", db_path=self.db_path)
        self.assertEqual(r.returncode, 0)
        # with vi/el/fr filter, both meanings should show gaps
        self.assertIn("ocean", r.stdout)


class TestBatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)

    def test_batch_creates_meaning_and_words(self):
        batch_input = textwrap.dedent("""\
            = star
            en star
            ja 星 r:hoshi
            fr étoile g:f
        """)
        r = run_cli("batch", db_path=self.db_path, stdin=batch_input)
        self.assertEqual(r.returncode, 0, r.stderr)

        # verify meaning exists
        r2 = run_cli("meanings", db_path=self.db_path)
        self.assertIn("star", r2.stdout)

        # verify words exist with correct meanings
        r3 = run_cli("words", "-m", "star", db_path=self.db_path)
        self.assertIn("star", r3.stdout)
        self.assertIn("星", r3.stdout)
        self.assertIn("étoile", r3.stdout)

    def test_batch_shows_translations_via_shared_meaning(self):
        batch_input = textwrap.dedent("""\
            = ocean
            en ocean
            ja 海 r:umi
        """)
        r = run_cli("batch", db_path=self.db_path, stdin=batch_input)
        self.assertEqual(r.returncode, 0, r.stderr)

        # translations derived from shared meaning, not explicit links
        r2 = run_cli("show", "ocean:en", db_path=self.db_path)
        self.assertIn("海", r2.stdout)
        self.assertIn("translation", r2.stdout)

    def test_batch_multiple_blocks(self):
        batch_input = textwrap.dedent("""\
            = star
            en star
            ja 星 r:hoshi

            = moon
            en moon
            ja 月 r:tsuki
        """)
        r = run_cli("batch", db_path=self.db_path, stdin=batch_input)
        self.assertEqual(r.returncode, 0, r.stderr)

        r2 = run_cli("meanings", db_path=self.db_path)
        self.assertIn("star", r2.stdout)
        self.assertIn("moon", r2.stdout)

    def test_batch_skips_existing_words(self):
        # pre-create a word
        run_cli("add-meaning", "star", db_path=self.db_path)
        run_cli("add-word", "star", "en", "-m", "star", db_path=self.db_path)

        batch_input = textwrap.dedent("""\
            = star
            en star
            ja 星 r:hoshi
        """)
        r = run_cli("batch", db_path=self.db_path, stdin=batch_input)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("skip", r.stdout.lower())

        # should still create the japanese word and link it
        r2 = run_cli("show", "star:en", db_path=self.db_path)
        self.assertIn("星", r2.stdout)

    def test_batch_with_note(self):
        batch_input = textwrap.dedent("""\
            = star
            en star n:also means celebrity
        """)
        r = run_cli("batch", db_path=self.db_path, stdin=batch_input)
        self.assertEqual(r.returncode, 0, r.stderr)

        r2 = run_cli("show", "star:en", db_path=self.db_path)
        self.assertIn("celebrity", r2.stdout)

    def test_batch_word_with_multiple_meanings(self):
        batch_input = textwrap.dedent("""\
            = star
            en star

            = light
            en star
        """)
        r = run_cli("batch", db_path=self.db_path, stdin=batch_input)
        self.assertEqual(r.returncode, 0, r.stderr)

        # star should have both meanings
        r2 = run_cli("show", "star:en", db_path=self.db_path)
        self.assertIn("star", r2.stdout)
        self.assertIn("light", r2.stdout)

    def test_batch_comments_and_blank_lines(self):
        batch_input = textwrap.dedent("""\
            # this is a comment
            = star
            en star
            # another comment
            ja 星 r:hoshi

        """)
        r = run_cli("batch", db_path=self.db_path, stdin=batch_input)
        self.assertEqual(r.returncode, 0, r.stderr)

        r2 = run_cli("words", "-m", "star", db_path=self.db_path)
        self.assertIn("star", r2.stdout)
        self.assertIn("星", r2.stdout)

    def test_batch_dry_run(self):
        batch_input = textwrap.dedent("""\
            = star
            en star
            ja 星 r:hoshi
        """)
        r = run_cli("batch", "--dry-run", db_path=self.db_path, stdin=batch_input)
        self.assertEqual(r.returncode, 0, r.stderr)

        # nothing should be created
        r2 = run_cli("meanings", db_path=self.db_path)
        self.assertNotIn("star", r2.stdout)


class TestLink(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "snow", db_path=self.db_path)
        run_cli("add-meaning", "bravery", db_path=self.db_path)
        run_cli("add-word", "雪", "ja", "-r", "yuki", "-m", "snow", db_path=self.db_path)
        run_cli("add-word", "勇気", "ja", "-r", "yūki", "-m", "bravery", db_path=self.db_path)

    def test_link_soundalike(self):
        r = run_cli("link", "雪:ja", "勇気:ja", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = run_cli("show", "雪:ja", db_path=self.db_path)
        self.assertIn("勇気", r2.stdout)
        self.assertIn("sound-alike", r2.stdout)

    def test_link_rejects_translation_type(self):
        r = run_cli("link", "雪:ja", "勇気:ja", "-t", "translation", db_path=self.db_path)
        self.assertNotEqual(r.returncode, 0)


class TestTransitiveSoundalikes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        # A sounds like B, B sounds like C — A should transitively sound like C
        run_cli("add-meaning", "strength", db_path=self.db_path)
        run_cli("add-meaning", "perseverance", db_path=self.db_path)
        run_cli("add-meaning", "bright", db_path=self.db_path)
        run_cli("add-word", "Ken", "en", "-m", "bright", db_path=self.db_path)
        run_cli("add-word", "健", "ja", "-r", "ken", "-m", "strength", db_path=self.db_path)
        run_cli("add-word", "Kiên", "vi", "-m", "perseverance", db_path=self.db_path)
        run_cli("link", "Ken:en", "健:ja", db_path=self.db_path)
        run_cli("link", "健:ja", "Kiên:vi", db_path=self.db_path)

    def test_transitive_soundalike(self):
        """Ken(en) ↔ 健(ja) ↔ Kiên(vi) implies Ken(en) ↔ Kiên(vi)."""
        r = run_cli("show", "Ken:en", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("健", r.stdout)
        self.assertIn("Kiên", r.stdout)

    def test_transitive_soundalike_reverse(self):
        """transitivity works from the other end too."""
        r = run_cli("show", "Kiên:vi", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Ken", r.stdout)
        self.assertIn("健", r.stdout)

    def test_soundalike_no_duplicates(self):
        """each word appears at most once even with multiple paths."""
        # add a fourth word linked to both Ken and Kiên (creating a cycle)
        run_cli("add-meaning", "wise", db_path=self.db_path)
        run_cli("add-word", "賢", "ja", "-r", "ken", "-m", "wise", db_path=self.db_path)
        run_cli("link", "Ken:en", "賢:ja:ken", db_path=self.db_path)
        run_cli("link", "賢:ja:ken", "Kiên:vi", db_path=self.db_path)

        r = run_cli("show", "Ken:en", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        # count occurrences of each word in the sound-alikes section
        lines = r.stdout.split("\n")
        in_soundalikes = False
        sa_lines = []
        for line in lines:
            if "sound-alike" in line and "──" in line:
                in_soundalikes = True
                continue
            if in_soundalikes and "──" in line:
                break
            if in_soundalikes:
                sa_lines.append(line)
        sa_text = "\n".join(sa_lines)
        self.assertEqual(sa_text.count("Kiên"), 1)
        self.assertEqual(sa_text.count("賢"), 1)


class TestShowSoundalikesBeforeTranslations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "ocean", db_path=self.db_path)
        run_cli("add-meaning", "bravery", db_path=self.db_path)
        run_cli("add-word", "ocean", "en", "-m", "ocean", db_path=self.db_path)
        run_cli("add-word", "海", "ja", "-r", "umi", "-m", "ocean", db_path=self.db_path)
        run_cli("add-word", "勇気", "ja", "-r", "yūki", "-m", "bravery", db_path=self.db_path)
        run_cli("link", "海:ja", "勇気:ja", db_path=self.db_path)

    def test_soundalikes_before_translations_in_show(self):
        """sound-alikes section appears before translations in CLI output."""
        r = run_cli("show", "海:ja:umi", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        sa_pos = r.stdout.index("sound-alike")
        tr_pos = r.stdout.index("translation")
        self.assertLess(sa_pos, tr_pos)


class TestShowTranslations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)

    def test_show_translations_from_shared_meaning(self):
        """words sharing a meaning appear as translations without explicit links."""
        run_cli("add-meaning", "star", db_path=self.db_path)
        run_cli("add-word", "star", "en", "-m", "star", db_path=self.db_path)
        run_cli("add-word", "星", "ja", "-r", "hoshi", "-m", "star", db_path=self.db_path)
        run_cli("add-word", "Sao", "vi", "-m", "star", db_path=self.db_path)

        r = run_cli("show", "star:en", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("星", r.stdout)
        self.assertIn("Sao", r.stdout)
        self.assertIn("translation", r.stdout)

    def test_show_no_self_in_translations(self):
        """the word itself should not appear in its own translations list."""
        run_cli("add-meaning", "star", db_path=self.db_path)
        run_cli("add-word", "star", "en", "-m", "star", db_path=self.db_path)
        run_cli("add-word", "星", "ja", "-r", "hoshi", "-m", "star", db_path=self.db_path)

        r = run_cli("show", "star:en", db_path=self.db_path)
        # count occurrences of "star" — should appear in header/meanings but not translations list
        lines = r.stdout.split("\n")
        translation_section = False
        for line in lines:
            if "translation" in line and "──" in line:
                translation_section = True
                continue
            if translation_section and line.strip().startswith("star"):
                self.fail("word appears in its own translations")


class TestTrace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        # build a chain: A ↔ B ↔ C ↔ D
        run_cli("add-meaning", "strength", db_path=self.db_path)
        run_cli("add-meaning", "bright", db_path=self.db_path)
        run_cli("add-meaning", "perseverance", db_path=self.db_path)
        run_cli("add-meaning", "wise", db_path=self.db_path)
        run_cli("add-word", "Ken", "en", "-m", "bright", db_path=self.db_path)
        run_cli("add-word", "健", "ja", "-r", "ken", "-m", "strength", db_path=self.db_path)
        run_cli("add-word", "Kiên", "vi", "-m", "perseverance", db_path=self.db_path)
        run_cli("add-word", "賢", "ja", "-r", "ken", "-m", "wise", db_path=self.db_path)
        run_cli("link", "Ken:en", "健:ja", db_path=self.db_path)
        run_cli("link", "健:ja", "Kiên:vi", db_path=self.db_path)
        run_cli("link", "Kiên:vi", "賢:ja:ken", db_path=self.db_path)

    def test_trace_shows_direct_links(self):
        r = run_cli("trace", "Ken:en", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        # 健 is a direct link from Ken
        self.assertIn("健", r.stdout)

    def test_trace_shows_path_for_indirect(self):
        """indirect sound-alikes show which word they were reached through."""
        r = run_cli("trace", "Ken:en", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.strip().split("\n")
        # Kiên should show it was reached via 健
        kien_line = [l for l in lines if "Kiên" in l][0]
        self.assertIn("健", kien_line)

    def test_trace_shows_depth(self):
        """words further in the chain have higher depth."""
        r = run_cli("trace", "Ken:en", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.strip().split("\n")
        # 健 at depth 1, Kiên at depth 2, 賢 at depth 3
        ken_ja_line = [l for l in lines if "健" in l][0]
        kien_line = [l for l in lines if "Kiên" in l][0]
        ken_wise_line = [l for l in lines if "賢" in l][0]
        # deeper words should have more indentation
        self.assertGreater(len(kien_line) - len(kien_line.lstrip()),
                           len(ken_ja_line) - len(ken_ja_line.lstrip()))
        self.assertGreater(len(ken_wise_line) - len(ken_wise_line.lstrip()),
                           len(kien_line) - len(kien_line.lstrip()))

    def test_trace_no_results(self):
        """word with no sound-alikes shows a message."""
        run_cli("add-meaning", "ocean", db_path=self.db_path)
        run_cli("add-word", "ocean", "en", "-m", "ocean", db_path=self.db_path)
        r = run_cli("trace", "ocean:en", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no sound-alikes", r.stdout)


class TestRemoveWord(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "ocean", db_path=self.db_path)
        run_cli("add-word", "ocean", "en", "-m", "ocean", db_path=self.db_path)
        run_cli("add-word", "海", "ja", "-r", "umi", "-m", "ocean", db_path=self.db_path)
        run_cli("link", "ocean:en", "海:ja", db_path=self.db_path)

    def test_remove_word_deletes_it(self):
        r = run_cli("remove-word", "ocean:en", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = run_cli("words", db_path=self.db_path)
        self.assertNotIn("ocean [en]", r2.stdout)

    def test_remove_word_cascades_links(self):
        r = run_cli("remove-word", "ocean:en", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = run_cli("show", "海:ja:umi", db_path=self.db_path)
        self.assertNotIn("sound-alike", r2.stdout)

    def test_remove_word_not_found(self):
        r = run_cli("remove-word", "nope:en", db_path=self.db_path)
        self.assertNotEqual(r.returncode, 0)


class TestUnlink(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "snow", db_path=self.db_path)
        run_cli("add-meaning", "bravery", db_path=self.db_path)
        run_cli("add-word", "雪", "ja", "-r", "yuki", "-m", "snow", db_path=self.db_path)
        run_cli("add-word", "勇気", "ja", "-r", "yūki", "-m", "bravery", db_path=self.db_path)
        run_cli("link", "雪:ja", "勇気:ja", db_path=self.db_path)

    def test_unlink_removes_link(self):
        r = run_cli("unlink", "雪:ja", "勇気:ja", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = run_cli("show", "雪:ja", db_path=self.db_path)
        self.assertNotIn("sound-alike", r2.stdout)

    def test_unlink_no_link(self):
        run_cli("add-word", "snow", "en", "-m", "snow", db_path=self.db_path)
        r = run_cli("unlink", "snow:en", "雪:ja", db_path=self.db_path)
        self.assertNotEqual(r.returncode, 0)


class TestEditWord(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "dawn", db_path=self.db_path)
        run_cli("add-word", "dawn", "en", "-m", "dawn", db_path=self.db_path)

    def test_edit_text(self):
        r = run_cli("edit-word", "dawn:en", "--text", "Dawn", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = run_cli("words", db_path=self.db_path)
        self.assertIn("Dawn", r2.stdout)

    def test_edit_gender(self):
        r = run_cli("edit-word", "dawn:en", "--gender", "f", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = run_cli("words", db_path=self.db_path)
        self.assertIn("[f]", r2.stdout)

    def test_edit_no_fields(self):
        r = run_cli("edit-word", "dawn:en", db_path=self.db_path)
        self.assertNotEqual(r.returncode, 0)


class TestRenameMeaning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "heaven", db_path=self.db_path)
        run_cli("add-word", "θεῖος", "el", "-m", "heaven", db_path=self.db_path)

    def test_rename_meaning(self):
        r = run_cli("rename-meaning", "heaven", "sky", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = run_cli("meanings", db_path=self.db_path)
        self.assertIn("sky", r2.stdout)
        self.assertNotIn("heaven", r2.stdout)

    def test_rename_preserves_words(self):
        run_cli("rename-meaning", "heaven", "sky", db_path=self.db_path)
        r = run_cli("words", "-m", "sky", db_path=self.db_path)
        self.assertIn("θεῖος", r.stdout)


class TestMergeMeanings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "courage", db_path=self.db_path)
        run_cli("add-meaning", "bravery", db_path=self.db_path)
        run_cli("add-word", "Courage", "fr", "-m", "courage", db_path=self.db_path)
        run_cli("add-word", "brave", "en", "-m", "bravery", db_path=self.db_path)

    def test_merge_moves_words(self):
        r = run_cli("merge-meanings", "courage", "bravery", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = run_cli("words", "-m", "bravery", db_path=self.db_path)
        self.assertIn("Courage", r2.stdout)
        self.assertIn("brave", r2.stdout)

    def test_merge_deletes_source(self):
        run_cli("merge-meanings", "courage", "bravery", db_path=self.db_path)
        r = run_cli("meanings", db_path=self.db_path)
        self.assertNotIn("courage", r.stdout)


class TestRemoveMeaning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "empty", db_path=self.db_path)
        run_cli("add-meaning", "used", db_path=self.db_path)
        run_cli("add-word", "test", "en", "-m", "used", db_path=self.db_path)

    def test_remove_empty_meaning(self):
        r = run_cli("remove-meaning", "empty", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = run_cli("meanings", db_path=self.db_path)
        self.assertNotIn("empty", r2.stdout)

    def test_remove_used_meaning_fails(self):
        r = run_cli("remove-meaning", "used", db_path=self.db_path)
        self.assertNotEqual(r.returncode, 0)


class TestUnassignMeaning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "star", db_path=self.db_path)
        run_cli("add-meaning", "light", db_path=self.db_path)
        run_cli("add-word", "star", "en", "-m", "star", db_path=self.db_path)
        run_cli("assign-meaning", "star:en", "light", db_path=self.db_path)

    def test_unassign_meaning(self):
        r = run_cli("unassign-meaning", "star:en", "light", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = run_cli("show", "star:en", db_path=self.db_path)
        self.assertNotIn("light", r2.stdout)
        self.assertIn("star", r2.stdout)

    def test_unassign_nonexistent(self):
        r = run_cli("unassign-meaning", "star:en", "ocean", db_path=self.db_path)
        self.assertNotEqual(r.returncode, 0)


class TestStats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "ocean", db_path=self.db_path)
        run_cli("add-word", "ocean", "en", "-m", "ocean", db_path=self.db_path)
        run_cli("add-word", "海", "ja", "-r", "umi", "-m", "ocean", db_path=self.db_path)

    def test_stats_output(self):
        r = run_cli("stats", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("words:", r.stdout)
        self.assertIn("meanings:", r.stdout)
        self.assertIn("en", r.stdout)
        self.assertIn("ja", r.stdout)


class TestWordsCount(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "ocean", db_path=self.db_path)
        run_cli("add-word", "ocean", "en", "-m", "ocean", db_path=self.db_path)
        run_cli("add-word", "海", "ja", "-r", "umi", "-m", "ocean", db_path=self.db_path)

    def test_words_count(self):
        r = run_cli("words", "--count", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("en", r.stdout)
        self.assertIn("ja", r.stdout)


class TestCoverageGapsOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "ocean", db_path=self.db_path)
        run_cli("add-meaning", "star", db_path=self.db_path)
        run_cli("add-word", "ocean", "en", "-m", "ocean", db_path=self.db_path)
        run_cli("add-word", "海", "ja", "-r", "umi", "-m", "ocean", db_path=self.db_path)
        run_cli("add-word", "star", "en", "-m", "star", db_path=self.db_path)

    def test_gaps_only_hides_complete(self):
        r = run_cli("coverage", "--gaps-only", "-l", "en", "ja", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        # ocean has both en and ja — should be hidden
        # star only has en — should show
        self.assertNotIn("ocean", r.stdout)
        self.assertIn("star", r.stdout)


class TestSuggestLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "ocean", db_path=self.db_path)
        run_cli("add-meaning", "snow", db_path=self.db_path)
        run_cli("add-meaning", "bravery", db_path=self.db_path)
        # identical romanized across languages — should score high
        run_cli("add-word", "穂", "ja", "-r", "ho", "-m", "ocean", db_path=self.db_path)
        run_cli("add-word", "호", "ko", "-r", "ho", "-m", "ocean", db_path=self.db_path)
        # already linked pair — should be excluded
        run_cli("add-word", "雪", "ja", "-r", "yuki", "-m", "snow", db_path=self.db_path)
        run_cli("add-word", "勇気", "ja", "-r", "yūki", "-m", "bravery", db_path=self.db_path)
        run_cli("link", "雪:ja", "勇気:ja", db_path=self.db_path)

    def test_suggest_links_finds_identical_romanized(self):
        r = run_cli("suggest-links", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("穂", r.stdout)
        self.assertIn("호", r.stdout)

    def test_suggest_links_excludes_already_linked(self):
        r = run_cli("suggest-links", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        # yuki/yūki are already linked — should not appear as suggestions
        lines = r.stdout.strip().split("\n")
        for line in lines:
            self.assertFalse("雪" in line and "勇気" in line,
                             "already-linked pair should not be suggested")

    def test_suggest_links_min_score(self):
        r = run_cli("suggest-links", "--min-score", "100", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        # only exact matches at score 100
        if r.stdout.strip():
            for line in r.stdout.strip().split("\n"):
                if line.strip() and not line.startswith("#"):
                    self.assertIn("100", line)

    def test_suggest_links_language_filter(self):
        r = run_cli("suggest-links", "-l", "ko", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        # should only include pairs involving ko
        lines = [l for l in r.stdout.strip().split("\n") if l.strip()]
        for line in lines:
            self.assertTrue("ko" in line, f"expected ko in line: {line}")

    def test_suggest_links_one_edit_distance(self):
        """words with one-character difference should be suggested."""
        run_cli("add-meaning", "spring", db_path=self.db_path)
        run_cli("add-meaning", "lotus", db_path=self.db_path)
        run_cli("add-word", "春", "ja", "-r", "haru", "-m", "spring", db_path=self.db_path)
        run_cli("add-word", "蓮", "ja", "-r", "hasu", "-m", "lotus", db_path=self.db_path)
        r = run_cli("suggest-links", "--min-score", "90", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.strip()
        self.assertTrue("春" in lines and "蓮" in lines,
                        "one-edit-distance pair should be suggested")


class TestSuggestMeanings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "ocean", db_path=self.db_path)
        run_cli("add-meaning", "water", db_path=self.db_path)
        # word A has both ocean and water
        run_cli("add-word", "海", "ja", "-r", "umi", "-m", "ocean", db_path=self.db_path)
        run_cli("assign-meaning", "海:ja:umi", "water", db_path=self.db_path)
        # word B shares ocean but not water
        run_cli("add-word", "ocean", "en", "-m", "ocean", db_path=self.db_path)

    def test_suggest_meanings_finds_missing(self):
        r = run_cli("suggest-meanings", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        # ocean [en] shares "ocean" with 海 which also has "water"
        # so "water" should be suggested for ocean [en]
        self.assertIn("ocean", r.stdout)
        self.assertIn("water", r.stdout)

    def test_suggest_meanings_no_duplicates(self):
        """should not suggest a meaning the word already has."""
        run_cli("assign-meaning", "ocean:en", "water", db_path=self.db_path)
        r = run_cli("suggest-meanings", db_path=self.db_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        # now ocean [en] already has water — nothing to suggest
        lines = [l for l in r.stdout.strip().split("\n") if "ocean" in l and "en" in l]
        for line in lines:
            self.assertNotIn("water", line)


class TestWebLanguages(unittest.TestCase):
    """integration tests for the /languages web route."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = make_db(self.tmp)
        run_cli("add-meaning", "ocean", db_path=self.db_path)
        run_cli("add-word", "ocean", "en", "-m", "ocean", db_path=self.db_path)
        run_cli("add-word", "海", "ja", "-r", "umi", "-m", "ocean", db_path=self.db_path)
        run_cli("add-word", "biển", "vi", "-m", "ocean", db_path=self.db_path)

        import web as web_mod
        web_mod.DB_PATH = self.db_path
        self.app = web_mod.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_languages_page_returns_200(self):
        r = self.client.get("/languages")
        self.assertEqual(r.status_code, 200)

    def test_languages_page_lists_all_languages(self):
        r = self.client.get("/languages")
        html = r.data.decode()
        self.assertIn("en", html)
        self.assertIn("ja", html)
        self.assertIn("vi", html)

    def test_languages_page_shows_word_counts(self):
        r = self.client.get("/languages")
        html = r.data.decode()
        # each language has 1 word
        self.assertIn("1", html)

    def test_languages_page_shows_meaning_counts(self):
        run_cli("add-meaning", "water", db_path=self.db_path)
        run_cli("assign-meaning", "海:ja:umi", "water", db_path=self.db_path)
        r = self.client.get("/languages")
        html = r.data.decode()
        # ja now has 2 meanings, en and vi have 1
        self.assertIn("2", html)

    def test_languages_page_links_to_language_detail(self):
        r = self.client.get("/languages")
        html = r.data.decode()
        self.assertIn('href="/language/en"', html)
        self.assertIn('href="/language/ja"', html)

    def test_nav_has_languages_link(self):
        r = self.client.get("/")
        html = r.data.decode()
        self.assertIn('href="/languages"', html)


if __name__ == "__main__":
    unittest.main()
