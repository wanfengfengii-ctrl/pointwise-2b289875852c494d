import unittest
from fractions import Fraction

from spectra import Archive
from tests.fixtures import OnePass, document, primary, table, header, card, numeric_card, snapshot


class SourceFailure(Exception):
    pass


class TestImportFailures(unittest.TestCase):
    def setUp(self):
        self.archive = Archive(":memory:")
        self.addCleanup(self.archive.close)
        self.old = self.archive.ingest(OnePass(document()))
        self.before = snapshot(self.archive._connection)

    def assert_rejected(self, data):
        with self.assertRaises(ValueError):
            self.archive.ingest(OnePass(data))
        self.assertEqual(snapshot(self.archive._connection), self.before)
        self.assertEqual(self.archive.cell(self.old, 0, "quality", 0, 1), (Fraction(2),))
        self.assertFalse(self.archive._connection.in_transaction)

    def test_invalid_layout(self):
        columns = [{"name": "j", "repeat": 2}]
        good = document(columns, [([1, 2],)])
        bad_width = primary() + table(columns, [([1, 2],)], overrides={"NAXIS1": 4})
        self.assert_rejected(bad_width)
        for cut in (1, 79, 2879, 2880, 5759, 5760, 5763, len(good) - 1):
            with self.subTest(cut=cut):
                self.assert_rejected(good[:cut])
        self.assert_rejected(primary())

    def test_header_padding(self):
        good = document()
        duplicate = header([
            card("SIMPLE", True), card("SIMPLE", True),
            card("BITPIX", 8), card("NAXIS", 0),
        ]) + good[2880:]
        self.assert_rejected(duplicate)
        missing_end = good[:240] + b" " * 2640 + good[2880:]
        self.assert_rejected(missing_end)
        for offset in (400, 2880 + 1600):
            bad = bytearray(good)
            bad[offset] = 88
            self.assert_rejected(bytes(bad))
        bad = bytearray(good)
        bad[10] = 255
        self.assert_rejected(bytes(bad))
        duplicate_column = primary() + table(
            [{"name": "j"}], [([1],)], extra=[card("TFORM1", "J")]
        )
        self.assert_rejected(duplicate_column)

    def test_trailing_hdu(self):
        good = document()
        for tail in (b"x", b" " * 80, primary(), b"XTENSION" + b" " * 100):
            with self.subTest(tail=tail[:12]):
                self.assert_rejected(good + tail)
        bad = bytearray(good)
        bad[5760 + 32] = 1
        self.assert_rejected(bytes(bad))
        second = table([{"name": "later"}], [([12],)])
        self.assert_rejected(good + second[:-1])
        self.assert_rejected(good + second[:200])

    def test_unsupported_tform(self):
        for tform in ("1PJ", "1QJ", "PJ(4)", "2I", "E", "0J", "-1J", "1K"):
            with self.subTest(tform=tform):
                self.assert_rejected(document(
                    [{"name": "x", "tform": tform}], [([1],)]
                ))

    def test_structural_headers(self):
        columns = [{"name": "x"}]
        for overrides in (
            {"BITPIX": 16}, {"NAXIS": 1}, {"NAXIS1": -1}, {"NAXIS2": -1},
            {"GCOUNT": 2}, {"PCOUNT": 4}, {"TFIELDS": 2},
            {"XTENSION": "IMAGE"}, {"NAXIS1": True},
        ):
            with self.subTest(overrides=overrides):
                self.assert_rejected(primary() + table(columns, [([1],)], overrides=overrides))
        for extra in (
            [card("THEAP", 5)], [card("NAXIS3", 1)], [card("ZTABLE", True)],
            [card("TFORM2", "J")],
        ):
            self.assert_rejected(primary() + table(columns, [([1],)], extra=extra))
        for key in ("BITPIX", "NAXIS1", "NAXIS2", "PCOUNT", "GCOUNT", "TFIELDS", "TFORM1", "TTYPE1"):
            raw = document(columns, [([1],)])
            start = raw.index(key.ljust(8).encode("ascii"), 2880)
            self.assert_rejected(raw[:start] + card("COMMENT") + raw[start + 80:])
        self.assert_rejected(document([{"name": "same"}, {"name": "same"}], [([1], [2])]))
        self.assert_rejected(document([{"name": " "}], [([1],)]))
        for options in ({"null": 2147483648}, {"null": True}, {"scale": "NaN"},
                        {"zero": "INF"}, {"scale": "'0.1'"}):
            self.assert_rejected(document([{"name": "x", **options}], [([1],)]))
        self.assert_rejected(primary() + table(columns, [([1],)], extra=[
            numeric_card("TNULL1", "1.5")
        ]))

    def test_source_exception(self):
        error = SourceFailure("source disappeared after two rows")
        data = document()
        archive = self.archive
        before = self.before
        old = self.old

        def source():
            yield data[:5760 + 32]
            # Both rows have reached storage, but data padding and EOF have not.
            self.assertEqual(archive._connection.execute(
                "SELECT count(*) FROM fixed_cells WHERE revision<>?", (old,)
            ).fetchone()[0], 4)
            with self.assertRaises(KeyError):
                archive.describe(old + 1)
            raise error

        with self.assertRaises(SourceFailure) as caught:
            archive.ingest(source())
        self.assertIs(caught.exception, error)
        self.assertEqual(snapshot(archive._connection), before)
        revision = archive.ingest(OnePass(document()))
        self.assertNotEqual(revision, old)

    def test_eof_source_exception_and_chunk_types(self):
        error = SourceFailure("EOF probe failed")

        def source():
            yield document()
            raise error

        with self.assertRaises(SourceFailure) as caught:
            self.archive.ingest(source())
        self.assertIs(caught.exception, error)
        self.assertEqual(snapshot(self.archive._connection), self.before)
        for invalid in ("bytes", bytearray(b"x"), None):
            with self.assertRaises(ValueError):
                self.archive.ingest(iter((document(), invalid)))
            self.assertEqual(snapshot(self.archive._connection), self.before)
