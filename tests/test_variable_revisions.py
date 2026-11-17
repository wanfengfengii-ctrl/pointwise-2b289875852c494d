import sqlite3
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from spectra import Archive
from tests.fixtures import OnePass, primary, document
from tests.variable_fixtures import vtable, expect_table, full_snapshot


V1_SCHEMA_SQL = """
CREATE TABLE revisions(
    revision INTEGER PRIMARY KEY,
    state TEXT NOT NULL CHECK(state IN ('staging','published')),
    table_count INTEGER NOT NULL DEFAULT 0,
    row_count INTEGER NOT NULL DEFAULT 0,
    cell_count INTEGER NOT NULL DEFAULT 0,
    input_bytes INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE tables(
    revision INTEGER NOT NULL REFERENCES revisions(revision) ON DELETE CASCADE,
    hdu_index INTEGER NOT NULL CHECK(hdu_index > 0),
    row_count INTEGER NOT NULL CHECK(row_count >= 0),
    row_width INTEGER NOT NULL CHECK(row_width >= 0),
    column_count INTEGER NOT NULL CHECK(column_count >= 0),
    PRIMARY KEY(revision,hdu_index)
);
CREATE TABLE columns(
    revision INTEGER NOT NULL,
    hdu_index INTEGER NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    name TEXT NOT NULL,
    repeat INTEGER NOT NULL CHECK(repeat > 0),
    tnull INTEGER,
    scale_num TEXT NOT NULL,
    scale_den TEXT NOT NULL,
    zero_num TEXT NOT NULL,
    zero_den TEXT NOT NULL,
    PRIMARY KEY(revision,hdu_index,ordinal),
    UNIQUE(revision,hdu_index,name),
    FOREIGN KEY(revision,hdu_index) REFERENCES tables(revision,hdu_index) ON DELETE CASCADE
);
CREATE TABLE fixed_cells(
    revision INTEGER NOT NULL,
    hdu_index INTEGER NOT NULL,
    row_index INTEGER NOT NULL CHECK(row_index >= 0),
    ordinal INTEGER NOT NULL,
    payload BLOB NOT NULL,
    PRIMARY KEY(revision,hdu_index,row_index,ordinal),
    FOREIGN KEY(revision,hdu_index,ordinal)
        REFERENCES columns(revision,hdu_index,ordinal) ON DELETE CASCADE
);
"""


def build_v1_archive(path):
    """Write a schema-version-1 archive exactly as the V1 code did."""
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript("BEGIN;\n" + V1_SCHEMA_SQL + "\nPRAGMA user_version=1;\nCOMMIT;")
        connection.execute(
            "INSERT INTO revisions(state,table_count,row_count,cell_count,input_bytes) "
            "VALUES ('published',1,1,2,5760)")
        connection.execute("INSERT INTO tables VALUES (1,1,1,12,2)")
        connection.execute(
            "INSERT INTO columns(revision,hdu_index,ordinal,name,repeat,tnull,"
            "scale_num,scale_den,zero_num,zero_den) VALUES (1,1,0,'quality',1,NULL,'1','1','0','1')")
        connection.execute(
            "INSERT INTO columns(revision,hdu_index,ordinal,name,repeat,tnull,"
            "scale_num,scale_den,zero_num,zero_den) VALUES (1,1,1,'flux',2,-999,'1','2','1','1')")
        connection.execute("INSERT INTO fixed_cells VALUES (1,1,0,0,?)",
                           ((4).to_bytes(4, "big", signed=True),))
        connection.execute("INSERT INTO fixed_cells VALUES (1,1,0,1,?)",
                           ((10).to_bytes(4, "big", signed=True)
                            + (-999).to_bytes(4, "big", signed=True),))
    finally:
        connection.close()


class TestVariableRevisions(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="spectra-variable-test-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "archive.sqlite"
        self.archive = Archive(self.path)
        self.addCleanup(self.close_archive)

    def close_archive(self):
        self.archive.close()

    def reopen(self):
        self.archive.close()
        self.archive = Archive(self.path)

    def test_source_deletion_append_and_reopen(self):
        kept = []
        for index, kind in enumerate(("P", "Q")):
            columns = [{"name": "q"},
                       {"name": "flux", "kind": kind, "null": -999, "scale": "0.5"}]
            heap = b"".join(v.to_bytes(4, "big", signed=True) for v in (10, -999, 30))
            rows = [([index + 1], (3, 0)), ([index + 2], (2, 4))]
            data = primary() + vtable(columns, rows, heap)
            source = Path(self.directory.name) / ("source-%d.fits" % index)
            source.write_bytes(data)
            with source.open("rb") as stream:
                revision = self.archive.ingest(iter(lambda: stream.read(41), b""))
            source.unlink()
            kept.append((revision, expect_table(columns, rows, heap)))
            self.reopen()
            for rev, expected in kept:
                for (row, name), values in expected.items():
                    self.assertEqual(
                        self.archive.cell(rev, row, (1, name), 0, 99), values)
        self.assertNotEqual(kept[0][0], kept[1][0])
        old = self.archive.ingest(OnePass(document()))
        self.assertEqual(self.archive.cell(old, 0, "quality", 0, 1), (Fraction(2),))
        self.reopen()
        for rev, expected in kept:
            for (row, name), values in expected.items():
                self.assertEqual(self.archive.cell(rev, row, (1, name), 0, 99), values)

    def test_close_lifecycle_variable(self):
        columns = [{"name": "flux", "kind": "P"}]
        revision = self.archive.ingest(
            OnePass(primary() + vtable(columns, [((1, 0),)], b"\0\0\0\2")))
        self.archive.close()
        self.archive.close()
        calls = (
            lambda: self.archive.ingest(()),
            lambda: self.archive.describe(revision),
            lambda: self.archive.cell(revision, 0, "flux", 0, 1),
            lambda: self.archive.select_rows(revision, "flux", 0, 9),
        )
        for call in calls:
            with self.assertRaises(RuntimeError):
                call()
        self.reopen()
        self.assertEqual(self.archive.cell(revision, 0, "flux", 0, 1), (Fraction(2),))

    def test_v1_archive_remains_readable_and_appendable(self):
        self.archive.close()
        self.path.unlink()
        build_v1_archive(self.path)
        self.archive = Archive(self.path)
        self.assertEqual(
            self.archive._connection.execute("PRAGMA user_version").fetchone()[0], 2)
        info = self.archive.describe(1)
        self.assertEqual([c["tform"] for c in info["tables"][0]["columns"]], ["1J", "2J"])
        self.assertEqual(self.archive.cell(1, 0, "flux", 0, 2), (Fraction(6), None))
        self.assertEqual(self.archive.select_rows(1, "quality", 4, 4), (0,))
        columns = [{"name": "flux", "kind": "Q", "scale": "2"}]
        data = primary() + vtable(columns, [((2, 0),)], b"\0\0\0\3" * 2)
        revision = self.archive.ingest(OnePass(data))
        self.assertNotEqual(revision, 1)
        self.assertEqual(self.archive.cell(revision, 0, "flux", 0, 2),
                         (Fraction(6), Fraction(6)))
        self.reopen()
        self.assertEqual(self.archive.cell(1, 0, "flux", 0, 2), (Fraction(6), None))
        self.assertEqual(self.archive.cell(revision, 0, "flux", 0, 2),
                         (Fraction(6), Fraction(6)))
        self.assertEqual(self.archive.describe(1), info)
