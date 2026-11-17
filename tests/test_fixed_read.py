import unittest
from fractions import Fraction

from spectra import Archive
from tests.fixtures import OnePass, document, primary, table


class TestFixedRead(unittest.TestCase):
    def setUp(self):
        self.archive = Archive(":memory:")
        self.addCleanup(self.archive.close)

    def test_null_before_scaling(self):
        columns = [
            {"name": "zero", "repeat": 3, "null": -999, "scale": "0", "zero": "7"},
            {"name": "negative", "repeat": 3, "null": -999, "scale": "-2", "zero": "1"},
        ]
        revision = self.archive.ingest(OnePass(document(columns, [
            ([-999, 0, 7], [-999, 0, 7]),
        ])))
        self.assertEqual(self.archive.cell(revision, 0, "zero", 0, 3),
                         (None, Fraction(7), Fraction(7)))
        self.assertEqual(self.archive.cell(revision, 0, "negative", 0, 3),
                         (None, Fraction(1), Fraction(-13)))
        self.assertEqual(self.archive.cell(revision, 0, "negative", 0, 2), (None, Fraction(1)))

    def test_exact_column_scales(self):
        columns = [
            {"name": "decimal", "repeat": 2, "scale": "0.1", "zero": "0.2"},
            {"name": "exponent", "repeat": 2, "scale": "-2.5D-1", "zero": "1E+2"},
        ]
        raw = [2147483647, -2147483648]
        revision = self.archive.ingest(OnePass(document(columns, [(raw, raw)])))
        self.assertEqual(self.archive.cell(revision, 0, "decimal", 0, 2),
                         tuple(Fraction(value, 10) + Fraction(1, 5) for value in raw))
        self.assertEqual(self.archive.cell(revision, 0, "exponent", 0, 2),
                         tuple(-Fraction(value, 4) + 100 for value in raw))
        info = self.archive.describe(revision)["tables"][0]["columns"]
        self.assertEqual((info[0]["tscal"], info[0]["tzero"]), (Fraction(1, 10), Fraction(1, 5)))
        self.assertEqual((info[1]["tscal"], info[1]["tzero"]), (Fraction(-1, 4), Fraction(100)))

    def test_selection_and_slices(self):
        columns = [
            {"name": "temperature", "null": -999, "scale": "-2", "zero": "10"},
            {"name": "flux", "repeat": 2}, {"name": "guard"},
        ]
        rows = [([raw], [100 + index, 200 + index], [900 + index])
                for index, raw in enumerate([4, -999, 2, 3, 9, 1])]
        revision = self.archive.ingest(OnePass(document(columns, rows)))
        selected = self.archive.select_rows(revision, "temperature", 2, Fraction(6))
        self.assertEqual(selected, (0, 2, 3))
        self.assertEqual([self.archive.cell(revision, row, "flux", 1, 2) for row in selected],
                         [(Fraction(200),), (Fraction(202),), (Fraction(203),)])
        self.assertEqual(self.archive.select_rows(revision, "temperature", 6, 6), (2,))
        with self.assertRaises(ValueError):
            self.archive.select_rows(revision, "flux", 0, 1000)
        for row in (0, 1):
            expected = tuple(Fraction(value) for value in rows[row][1])
            for start, stop in ((0, 0), (0, 1), (1, 2), (2, 2), (0, 99), (99, 100)):
                self.assertEqual(self.archive.cell(revision, row, "flux", start, stop),
                                 expected[start:stop])

    def test_exact_selection_endpoints(self):
        revision = self.archive.ingest(OnePass(document(
            [{"name": "x", "scale": "0.1", "zero": "0.2", "null": -999}],
            [([value],) for value in (2147483647, -999, 0, 1)],
        )))
        endpoint = Fraction(2147483647, 10) + Fraction(1, 5)
        self.assertEqual(self.archive.select_rows(revision, "x", endpoint, endpoint), (0,))
        self.assertEqual(self.archive.select_rows(revision, "x", Fraction(1, 5), Fraction(3, 10)), (2, 3))

    def test_invalid_access(self):
        revision = self.archive.ingest(OnePass(document()))
        for start, stop in ((True, 1), (0, False), (-1, 2), (0, -1), (1.0, 2),
                            (0, "2"), (2, 1), (None, 2)):
            with self.subTest(bounds=(start, stop)), self.assertRaises(ValueError):
                self.archive.cell(revision, 0, "flux", start, stop)
        for row in (-1, True, 0.0, "0"):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.archive.cell(revision, row, "flux", 0, 1)
        for lower, upper in ((True, 1), (0, False), (0.0, 2), (2, 1), (0, "2")):
            with self.assertRaises(ValueError):
                self.archive.select_rows(revision, "quality", lower, upper)
        for rev, row, column in ((999, 0, "flux"), (revision, 2, "flux"),
                                  (revision, 0, "missing"), (revision, 0, (9, "flux"))):
            with self.assertRaises(KeyError):
                self.archive.cell(rev, row, column, 0, 1)
        with self.assertRaises(KeyError):
            self.archive.describe(999)
        info = self.archive.describe(revision)
        info["tables"][0]["columns"][0]["name"] = "changed"
        info["tables"].clear()
        self.assertEqual(self.archive.describe(revision)["tables"][0]["columns"][0]["name"], "quality")
        first = self.archive.cell(revision, 0, "flux", 0, 2)
        changed = first + (Fraction(999),)
        self.assertNotEqual(first, changed)
        self.assertEqual(self.archive.cell(revision, 0, "flux", 0, 2), first)

    def test_qualified_columns(self):
        data = primary() + table([{"name": "x"}], [([1],)])
        data += table([{"name": "x"}], [([2],)])
        revision = self.archive.ingest(OnePass(data))
        self.assertEqual(self.archive.select_rows(revision, (2, "x"), 2, 2), (0,))
        for column in ("x", (0, "x"), (True, "x"), (3, "x"), (1, "missing"), ["x"]):
            with self.subTest(column=column), self.assertRaises(KeyError):
                self.archive.select_rows(revision, column, 0, 9)
        with self.assertRaises(KeyError):
            self.archive.select_rows(999, (1, "x"), 0, 9)
