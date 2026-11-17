import unittest
from fractions import Fraction

from spectra import Archive
from tests.fixtures import OnePass, document, primary, table, card


class TestFixedImport(unittest.TestCase):
    def setUp(self):
        self.archive = Archive(":memory:")
        self.addCleanup(self.archive.close)

    def test_scalar_and_vector(self):
        revision = self.archive.ingest(OnePass(document()))
        info = self.archive.describe(revision)
        self.assertEqual(info["revision"], revision)
        self.assertEqual(info["tables"][0]["row_count"], 2)
        columns = info["tables"][0]["columns"]
        self.assertEqual([column["name"] for column in columns], ["quality", "flux"])
        self.assertEqual([column["tform"] for column in columns], ["1J", "3J"])
        self.assertEqual(self.archive.cell(revision, 0, "quality", 0, 9), (Fraction(2),))
        self.assertEqual(self.archive.cell(revision, 1, "flux", 0, 9),
                         (Fraction(40), Fraction(50), Fraction(60)))
        self.assertEqual(self.archive.cell(revision, 0, "flux", 0, 3),
                         (Fraction(10), Fraction(-999), Fraction(30)))

    def test_chunked_cards(self):
        name = "O'NEIL/FLUX"
        data = document([{"name": name, "repeat": 2}], [([123, -456],)])
        for sizes in ((len(data),), (1,), (79, 1, 2, 2879), (81, 7, 4096)):
            with self.subTest(sizes=sizes):
                source = OnePass(data, sizes)
                revision = self.archive.ingest(source)
                self.assertEqual(source.iterations, 1)
                self.assertEqual(self.archive.describe(revision)["tables"][0]["columns"][0]["name"], name)
                self.assertEqual(self.archive.cell(revision, 0, name, 0, 2),
                                 (Fraction(123), Fraction(-456)))

    def test_signed_j(self):
        values = [-2147483648, -16711936, -1, 0, 16909060, 2147483647]
        revision = self.archive.ingest(OnePass(document(
            [{"name": "j", "repeat": len(values)}], [(values,)]
        )))
        self.assertEqual(self.archive.cell(revision, 0, "j", 0, 99),
                         tuple(Fraction(value) for value in values))

    def test_column_offsets(self):
        columns = [{"name": "a"}, {"name": "b", "repeat": 3}, {"name": "c"}]
        rows = [([11], [12, 13, 14], [15]), ([21], [22, 23, 24], [25])]
        revision = self.archive.ingest(OnePass(document(columns, rows), (3, 17)))
        for row, cells in enumerate(rows):
            for column, values in zip(columns, cells):
                self.assertEqual(self.archive.cell(revision, row, column["name"], 0, 99),
                                 tuple(Fraction(value) for value in values))

    def test_multi_hdu_catalog(self):
        first = table([{"name": "same"}], [([7],)])
        second = table([{"name": "same", "repeat": 2}], [([8, 9],)])
        revision = self.archive.ingest(OnePass(primary() + first + second))
        self.assertEqual([entry["hdu_index"] for entry in self.archive.describe(revision)["tables"]], [1, 2])
        self.assertEqual(self.archive.cell(revision, 0, (1, "same"), 0, 9), (Fraction(7),))
        self.assertEqual(self.archive.cell(revision, 0, (2, "same"), 0, 9), (Fraction(8), Fraction(9)))
        with self.assertRaises(KeyError):
            self.archive.cell(revision, 0, "same", 0, 1)

    def test_zero_rows_and_explicit_theap(self):
        empty = table([{"name": "empty"}], [], extra=[card("THEAP", 0)])
        full = table([{"name": "j", "tform": "J"}], [([31],)], extra=[card("THEAP", 4)])
        revision = self.archive.ingest(OnePass(primary() + empty + full))
        self.assertEqual(self.archive.describe(revision)["tables"][0]["row_count"], 0)
        self.assertEqual(self.archive.select_rows(revision, "empty", 0, 100), ())
        with self.assertRaises(KeyError):
            self.archive.cell(revision, 0, "empty", 0, 1)
        self.assertEqual(self.archive.cell(revision, 0, "j", 0, 1), (Fraction(31),))
