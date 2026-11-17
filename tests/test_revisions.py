from pathlib import Path
import sqlite3
import tempfile
import unittest
from fractions import Fraction

from spectra import Archive
from tests.fixtures import OnePass, document, snapshot


class TestRevisions(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="spectra-test-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "archive.sqlite"
        self.archive = Archive(self.path)
        self.addCleanup(self.close_archive)

    def close_archive(self):
        self.archive.close()

    def reopen(self):
        self.archive.close()
        self.archive = Archive(self.path)

    def test_append_and_reopen(self):
        columns = [
            {"name": "quality", "scale": "0.1", "zero": "0.2"},
            {"name": "flux", "repeat": 2, "null": -999, "scale": "-0.5"},
        ]
        versions = [
            ([([1], [10, -999]), ([2], [30, 40])], (Fraction(-5), None)),
            ([([20], [50, 60]), ([30], [-999, 80])], (Fraction(77), Fraction(92))),
        ]
        revisions = []
        expected = []
        for index, (rows, window) in enumerate(versions):
            source = Path(self.directory.name) / f"observation-{index}.fits"
            current_columns = [dict(column) for column in columns]
            if index == 1:
                current_columns[0].update(scale="0.2", zero="-1")
                current_columns[1].update(scale="1.5", zero="2")
            source.write_bytes(document(current_columns, rows))
            with source.open("rb") as stream:
                revision = self.archive.ingest(iter(lambda: stream.read(83), b""))
            source.unlink()
            revisions.append(revision)
            expected.append((self.archive.describe(revision), window))
            self.reopen()
            for old, (metadata, old_window) in zip(revisions, expected):
                self.assertEqual(self.archive.describe(old), metadata)
                self.assertEqual(self.archive.cell(old, 0, "flux", 0, 99), old_window)
                self.assertEqual(self.archive.describe(old)["tables"][0]["columns"][0]["tscal"],
                                 Fraction(1, 10) if old == revisions[0] else Fraction(1, 5))
            self.assertEqual(self.archive.select_rows(revisions[0], "quality", Fraction(3, 10), Fraction(2, 5)), (0, 1))
        self.assertNotEqual(*revisions)
        self.assertEqual(self.archive.select_rows(revisions[1], "quality", Fraction(3, 10), Fraction(2, 5)), ())
        self.assertEqual(self.archive.cell(revisions[0], 1, "flux", 0, 2), (Fraction(-15), Fraction(-20)))
        self.assertEqual(self.archive.cell(revisions[1], 1, "flux", 0, 2), (None, Fraction(122)))

    def test_close_lifecycle(self):
        revision = self.archive.ingest(OnePass(document()))
        self.archive.close()
        self.archive.close()
        calls = (
            lambda: self.archive.ingest(()),
            lambda: self.archive.describe(revision),
            lambda: self.archive.cell(revision, 0, "flux", 0, 1),
            lambda: self.archive.select_rows(revision, "quality", 0, 9),
        )
        for call in calls:
            with self.assertRaises(RuntimeError):
                call()
        self.reopen()
        self.assertEqual(self.archive.cell(revision, 0, "quality", 0, 1), (Fraction(2),))

    def test_publication_failure(self):
        old = self.archive.ingest(OnePass(document()))
        connection = self.archive._connection
        before = snapshot(connection)
        connection.execute(
            "CREATE TEMP TRIGGER deny_publication BEFORE UPDATE OF state ON revisions "
            "WHEN NEW.state='published' BEGIN SELECT RAISE(ABORT,'publication denied'); END"
        )
        try:
            with self.assertRaises(sqlite3.IntegrityError) as caught:
                self.archive.ingest(OnePass(document()))
            self.assertIn("publication denied", str(caught.exception))
            self.assertEqual(snapshot(connection), before)
            self.assertFalse(connection.in_transaction)
            self.assertEqual(self.archive.cell(old, 1, "flux", 1, 3), (Fraction(50), Fraction(60)))
        finally:
            connection.execute("DROP TRIGGER deny_publication")
        self.reopen()
        self.assertEqual(snapshot(self.archive._connection), before)
        new = self.archive.ingest(OnePass(document()))
        self.assertNotEqual(old, new)
        self.assertEqual(self.archive.cell(old, 0, "quality", 0, 1), (Fraction(2),))
