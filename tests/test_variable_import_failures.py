import sqlite3
import unittest
from fractions import Fraction

from spectra import Archive
from tests.fixtures import OnePass, primary, document
from tests.variable_fixtures import vtable, full_snapshot


class TestVariableImportFailures(unittest.TestCase):
    def setUp(self):
        self.archive = Archive(":memory:")
        self.addCleanup(self.archive.close)
        self.old = self.archive.ingest(OnePass(document()))
        self.before = full_snapshot(self.archive._connection)

    def assert_rejected(self, data):
        with self.assertRaises(ValueError):
            self.archive.ingest(OnePass(data))
        self.assertEqual(full_snapshot(self.archive._connection), self.before)
        self.assertFalse(self.archive._connection.in_transaction)
        self.assertEqual(self.archive.cell(self.old, 0, "quality", 0, 1), (Fraction(2),))

    def test_invalid_descriptors(self):
        heap = b"\0" * 12
        for kind in ("P", "Q"):
            columns = [{"name": "flux", "kind": kind}]
            for descriptor in ((-1, 0), (1, -1), (1, 9), (2, 8), (1, 12), (4, 0)):
                with self.subTest(kind=kind, descriptor=descriptor):
                    bad = primary() + vtable(columns, [((1, 0),), (descriptor,)], heap)
                    self.assert_rejected(bad)

    def test_invalid_theap_and_pcount(self):
        columns = [{"name": "flux", "kind": "P"}]
        heap = b"\0" * 8
        self.assert_rejected(primary() + vtable(columns, [((1, 0),)], heap, theap=0))
        self.assert_rejected(primary() + vtable(columns, [((1, 0),)], heap, theap=999))
        self.assert_rejected(primary() + vtable(columns, [((1, 0),)], heap, theap="x"))
        self.assert_rejected(primary() + vtable(columns, [((1, 0),)], heap, pcount=-1))
        # Fixed-only tables keep the V1 rules: PCOUNT must be zero and no gap.
        self.assert_rejected(primary() + vtable([{"name": "j"}], [([1],)], b"\0" * 4))
        self.assert_rejected(primary() + vtable([{"name": "j"}], [([1],)], gap=b"g"))

    def test_unsupported_variable_tforms(self):
        for tform in ("2PJ", "PJ(4)", "0PJ", "P J", "1PJJ", "PQ", "1PJx", "1pJ", "1Q"):
            with self.subTest(tform=tform):
                columns = [{"name": "x", "kind": "P", "tform": tform}]
                self.assert_rejected(primary() + vtable(columns, [((0, 0),)]))

    def test_descriptor_width_mismatch(self):
        # A Q descriptor is sixteen row bytes; eight is a P descriptor.
        columns = [{"name": "flux", "kind": "Q"}]
        data = primary() + vtable(columns, [((1, 0),)], b"\0" * 4)
        self.assert_rejected(data.replace(b"NAXIS1  = 16", b"NAXIS1  = 8 ", 1))

    def test_late_failure_after_valid_hdu(self):
        columns = [{"name": "flux", "kind": "P"}]
        good = vtable(columns, [((1, 0),)], b"\0\0\0\5")
        bad = vtable(columns, [((1, 0),), ((9, 0),)], b"\0" * 8)
        self.assert_rejected(primary() + good + bad)

    def test_heap_truncation_padding_and_trailing(self):
        columns = [{"name": "flux", "kind": "P"}]
        good = primary() + vtable(columns, [((2, 0),)], b"\0\0\0\1" * 2)
        self.assert_rejected(good[:-1])                 # truncated data padding
        self.assert_rejected(good[:5760 + 8 + 4])       # truncated inside the heap
        bad = bytearray(good)
        bad[-1] = 1                                     # nonzero data padding
        self.assert_rejected(bytes(bad))
        self.assert_rejected(good + b"x")               # trailing junk
        self.assert_rejected(good + primary())          # trailing HDU

    def test_source_failure_mid_heap(self):
        error = LookupError("heap source vanished")
        columns = [{"name": "flux", "kind": "Q"}]
        data = primary() + vtable(columns, [((3, 0),)], b"\0\0\0\7" * 3)
        head = data[:5760 + 16 + 4]

        def source():
            yield head
            raise error

        with self.assertRaises(LookupError) as caught:
            self.archive.ingest(source())
        self.assertIs(caught.exception, error)
        self.assertEqual(full_snapshot(self.archive._connection), self.before)
        self.assertFalse(self.archive._connection.in_transaction)
        revision = self.archive.ingest(OnePass(document()))
        self.assertNotEqual(revision, self.old)

    def test_publication_failure_rolls_back_variable_content(self):
        connection = self.archive._connection
        connection.execute(
            "CREATE TEMP TRIGGER deny_publication BEFORE UPDATE OF state ON revisions "
            "WHEN NEW.state='published' BEGIN SELECT RAISE(ABORT,'publication denied'); END"
        )
        columns = [{"name": "flux", "kind": "P"}]
        data = primary() + vtable(columns, [((2, 0),)], b"\0\0\0\1" * 2)
        try:
            with self.assertRaises(sqlite3.IntegrityError) as caught:
                self.archive.ingest(OnePass(data))
            self.assertIn("publication denied", str(caught.exception))
            self.assertEqual(full_snapshot(connection), self.before)
            self.assertFalse(connection.in_transaction)
        finally:
            connection.execute("DROP TRIGGER deny_publication")
        revision = self.archive.ingest(OnePass(data))
        self.assertEqual(self.archive.cell(revision, 0, "flux", 0, 2),
                         (Fraction(1), Fraction(1)))
        self.assertEqual(self.archive.cell(self.old, 0, "quality", 0, 1), (Fraction(2),))
