import unittest
from fractions import Fraction

from spectra import Archive
from tests.fixtures import OnePass, primary
from tests.variable_fixtures import vtable, expect_table, big_source


class TestVariableRead(unittest.TestCase):
    def setUp(self):
        self.archive = Archive(":memory:")
        self.addCleanup(self.archive.close)

    def test_overlap_unaligned_unordered_independent_interpretation(self):
        heap = bytes(range(16))
        columns = [
            {"name": "a", "kind": "P", "null": 0x05060708, "scale": "2"},
            {"name": "b", "kind": "P", "null": 0x05060708, "scale": "-1", "zero": "10"},
        ]
        rows = [
            ((4, 0), (4, 0)),    # identical range, different interpretation
            ((2, 2), (2, 5)),    # unaligned starts; b's first element is its null
            ((4, 0), (2, 2)),    # the same references in the other order
            ((1, 12), (1, 12)),  # single tail elements
            ((1, 5), (2, 4)),    # a's element is its null
        ]
        revision = self.archive.ingest(OnePass(primary() + vtable(columns, rows, heap)))
        expected = expect_table(columns, rows, heap)
        self.assertEqual(expected[1, "b"][0], None)      # unaligned raw null hit
        self.assertEqual(expected[4, "a"], (None,))      # raw null before scaling
        for (row, name), values in expected.items():
            for start, stop in ((0, 99), (0, 0), (1, 2), (2, 9), (99, 100), (1, 1)):
                with self.subTest(row=row, name=name, window=(start, stop)):
                    self.assertEqual(
                        self.archive.cell(revision, row, (1, name), start, stop),
                        values[start:stop])
        self.assertNotEqual(expected[0, "a"], expected[0, "b"])

    def test_repeated_offsets_share_bytes_not_interpretation(self):
        heap = b"".join(v.to_bytes(4, "big", signed=True) for v in (10, -999, 30))
        columns = [
            {"name": "flux", "kind": "Q", "null": -999, "scale": "0.5", "zero": "1"},
            {"name": "other", "kind": "Q", "null": 10, "scale": "-2"},
        ]
        rows = [((3, 0), (3, 0)), ((2, 4), (2, 4)), ((0, -123), (0, -1))]
        revision = self.archive.ingest(OnePass(primary() + vtable(columns, rows, heap)))
        expected = expect_table(columns, rows, heap)
        self.assertEqual(expected[0, "flux"], (Fraction(6), None, Fraction(16)))
        self.assertEqual(expected[0, "other"], (None, Fraction(1998), Fraction(-60)))
        self.assertEqual(expected[2, "flux"], expected[2, "other"], ())
        for (row, name), values in expected.items():
            self.assertEqual(self.archive.cell(revision, row, (1, name), 0, 99), values)

    def test_null_before_scaling_variable(self):
        heap = b"".join(v.to_bytes(4, "big", signed=True) for v in (-999, 0, 7))
        columns = [
            {"name": "zero", "kind": "Q", "null": -999, "scale": "0", "zero": "7"},
            {"name": "neg", "kind": "Q", "null": -999, "scale": "-2", "zero": "1"},
        ]
        revision = self.archive.ingest(
            OnePass(primary() + vtable(columns, [((3, 0), (3, 0))], heap)))
        self.assertEqual(self.archive.cell(revision, 0, "zero", 0, 3),
                         (None, Fraction(7), Fraction(7)))
        self.assertEqual(self.archive.cell(revision, 0, "neg", 0, 3),
                         (None, Fraction(1), Fraction(-13)))
        self.assertEqual(self.archive.cell(revision, 0, "neg", 0, 2), (None, Fraction(1)))

    def test_window_clipped_per_cell_count(self):
        heap = b"\0\0\0\1" * 3
        columns = [{"name": "flux", "kind": "P"}]
        rows = [((3, 0),), ((1, 8),), ((0, 0),)]
        revision = self.archive.ingest(OnePass(primary() + vtable(columns, rows, heap)))
        self.assertEqual(self.archive.cell(revision, 0, "flux", 1, 99),
                         (Fraction(1), Fraction(1)))
        self.assertEqual(self.archive.cell(revision, 1, "flux", 0, 1), (Fraction(1),))
        self.assertEqual(self.archive.cell(revision, 1, "flux", 1, 99), ())
        self.assertEqual(self.archive.cell(revision, 2, "flux", 0, 99), ())
        first = self.archive.cell(revision, 0, "flux", 0, 3)
        second = self.archive.cell(revision, 0, "flux", 0, 3)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)

    def test_window_spanning_heap_chunks(self):
        elements = 300000  # 1.2 MiB of heap: two stored chunks
        revision = self.archive.ingest(big_source("Q", elements, 3))
        boundary = (1 << 20) // 4
        window = self.archive.cell(revision, 2, "flux", boundary - 2, boundary + 2)
        self.assertEqual(window, (Fraction(7),) * 4)
        full = self.archive.cell(revision, 1, "flux", 0, elements)
        self.assertEqual(full, (Fraction(7),) * elements)
        self.assertEqual(self.archive.cell(revision, 0, "flux", elements - 1, elements),
                         (Fraction(7),))

    def test_invalid_access(self):
        columns = [{"name": "q"}, {"name": "flux", "kind": "P"}]
        data = primary() + vtable(columns, [([3], (1, 0))], b"\0\0\0\x09")
        revision = self.archive.ingest(OnePass(data))
        for start, stop in ((True, 1), (0, False), (-1, 2), (0, -1), (1.0, 2),
                            (0, "2"), (2, 1), (None, 2)):
            with self.subTest(bounds=(start, stop)), self.assertRaises(ValueError):
                self.archive.cell(revision, 0, "flux", start, stop)
        for row in (-1, True, 0.0, "0"):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.archive.cell(revision, row, "flux", 0, 1)
        for rev, row, column in ((999, 0, "flux"), (revision, 1, "flux"),
                                 (revision, 0, "missing"), (revision, 0, (9, "flux"))):
            with self.subTest(target=(rev, row, column)), self.assertRaises(KeyError):
                self.archive.cell(rev, row, column, 0, 1)
        with self.assertRaises(ValueError):
            self.archive.select_rows(revision, "flux", 0, 99)
        self.assertEqual(self.archive.select_rows(revision, "q", 3, 3), (0,))
        for lower, upper in ((True, 1), (0.0, 2), (2, 1)):
            with self.subTest(bounds=(lower, upper)), self.assertRaises(ValueError):
                self.archive.select_rows(revision, "q", lower, upper)

    def test_describe_is_fresh_and_independent(self):
        columns = [{"name": "flux", "kind": "Q", "null": -1, "scale": "0.25", "zero": "-3"}]
        data = primary() + vtable(columns, [((1, 0),)], b"\0\0\0\4")
        revision = self.archive.ingest(OnePass(data))
        info = self.archive.describe(revision)
        column = info["tables"][0]["columns"][0]
        self.assertEqual(column["tform"], "1QJ")
        self.assertEqual(column["repeat"], 1)
        self.assertEqual((column["tscal"], column["tzero"]), (Fraction(1, 4), Fraction(-3)))
        info["tables"][0]["columns"][0]["name"] = "changed"
        info["tables"].clear()
        again = self.archive.describe(revision)
        self.assertEqual(again["tables"][0]["columns"][0]["name"], "flux")
