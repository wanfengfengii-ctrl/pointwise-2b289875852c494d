import unittest
from fractions import Fraction

from spectra import Archive
from tests.fixtures import OnePass, primary, document
from tests.variable_fixtures import vtable, expect_table


class TestVariableImport(unittest.TestCase):
    def setUp(self):
        self.archive = Archive(":memory:")
        self.addCleanup(self.archive.close)

    def test_canonical_forms_and_metadata(self):
        heap = (5).to_bytes(4, "big", signed=True) + (-7).to_bytes(4, "big", signed=True)
        for form, canonical in (("PJ", "1PJ"), ("1PJ", "1PJ"), (" 1PJ ", "1PJ"),
                                ("QJ", "1QJ"), ("1QJ", "1QJ"), (" 1QJ ", "1QJ")):
            with self.subTest(form=form):
                kind = "P" if "P" in form else "Q"
                columns = [{"name": "flux", "kind": kind, "tform": form,
                            "null": -7, "scale": "0.5", "zero": "1"}]
                data = primary() + vtable(columns, [((2, 0),)], heap)
                revision = self.archive.ingest(OnePass(data))
                info = self.archive.describe(revision)["tables"][0]["columns"][0]
                self.assertEqual(info["tform"], canonical)
                self.assertEqual(info["repeat"], 1)
                self.assertEqual(info["tnull"], -7)
                self.assertEqual((info["tscal"], info["tzero"]),
                                 (Fraction(1, 2), Fraction(1)))
                self.assertEqual(self.archive.cell(revision, 0, "flux", 0, 9),
                                 (Fraction(7, 2), None))

    def test_mixed_table_gap_and_fixed_selection(self):
        heap = b"".join(v.to_bytes(4, "big", signed=True) for v in (10, -999, 30))
        columns = [
            {"name": "quality"},
            {"name": "flux", "kind": "Q", "null": -999, "scale": "0.5", "zero": "1"},
        ]
        rows = [([2], (3, 0)), ([5], (2, 4)), ([7], (0, -1))]
        data = primary() + vtable(columns, rows, heap, b"\x01gap!")
        revision = self.archive.ingest(OnePass(data, (1, 3, 2880, 17)))
        expected = expect_table(columns, rows, heap)
        for (row, name), values in expected.items():
            self.assertEqual(self.archive.cell(revision, row, (1, name), 0, 99), values)
        self.assertEqual(expected[2, "flux"], ())
        self.assertEqual(self.archive.select_rows(revision, "quality", 2, 5), (0, 1))
        info = self.archive.describe(revision)["tables"][0]
        self.assertEqual([c["tform"] for c in info["columns"]], ["1J", "1QJ"])

    def test_default_theap_and_zero_rows(self):
        columns = [{"name": "flux", "kind": "P"}]
        heap = b"\0\0\0\1" * 3
        data = primary() + vtable(columns, [((3, 0),)], heap, omit_theap=True)
        revision = self.archive.ingest(OnePass(data))
        self.assertEqual(self.archive.cell(revision, 0, "flux", 0, 3), (Fraction(1),) * 3)
        empty = primary() + vtable(columns, [], heap, omit_theap=True)
        revision = self.archive.ingest(OnePass(empty))
        self.assertEqual(self.archive.describe(revision)["tables"][0]["row_count"], 0)
        with self.assertRaises(KeyError):
            self.archive.cell(revision, 0, "flux", 0, 1)

    def test_multiple_hdus_keep_heap_offsets_local(self):
        columns = [{"name": "flux", "kind": "P"}]
        first = vtable(columns, [((2, 0),)], b"\0\0\0\1\0\0\0\2")
        second = vtable(columns, [((2, 0),)], b"\0\0\0\3\0\0\0\4")
        revision = self.archive.ingest(OnePass(primary() + first + second, (7, 4096)))
        self.assertEqual(self.archive.cell(revision, 0, (1, "flux"), 0, 2),
                         (Fraction(1), Fraction(2)))
        self.assertEqual(self.archive.cell(revision, 0, (2, "flux"), 0, 2),
                         (Fraction(3), Fraction(4)))
        with self.assertRaises(KeyError):
            self.archive.cell(revision, 0, "flux", 0, 1)

    def test_exact_heap_boundary(self):
        heap = b"\0\0\0\1" * 4
        columns = [{"name": "flux", "kind": "Q"}]
        rows = [((4, 0),), ((1, 12),), ((2, 8),), ((0, 16),), ((0, (1 << 63) - 1),)]
        revision = self.archive.ingest(OnePass(primary() + vtable(columns, rows, heap)))
        self.assertEqual(self.archive.cell(revision, 0, "flux", 0, 4), (Fraction(1),) * 4)
        self.assertEqual(self.archive.cell(revision, 1, "flux", 0, 1), (Fraction(1),))
        self.assertEqual(self.archive.cell(revision, 2, "flux", 0, 2), (Fraction(1),) * 2)
        self.assertEqual(self.archive.cell(revision, 3, "flux", 0, 9), ())
        self.assertEqual(self.archive.cell(revision, 4, "flux", 0, 9), ())

    def test_empty_heap_and_empty_descriptors(self):
        columns = [{"name": "flux", "kind": "P"}]
        rows = [((0, -2147483648),), ((0, 0),), ((0, 2147483647),)]
        revision = self.archive.ingest(OnePass(primary() + vtable(columns, rows)))
        for row in range(3):
            self.assertEqual(self.archive.cell(revision, row, "flux", 0, 9), ())

    def test_fixed_document_still_plain_v1(self):
        revision = self.archive.ingest(OnePass(document()))
        info = self.archive.describe(revision)["tables"][0]
        self.assertEqual([c["tform"] for c in info["columns"]], ["1J", "3J"])
        self.assertEqual(self.archive.cell(revision, 1, "flux", 0, 3),
                         (Fraction(40), Fraction(50), Fraction(60)))
