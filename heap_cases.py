"""Public V2 FITS specimens and independent small-byte checks; no archive implementation."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import resource
import sys
import tempfile
import tracemalloc

from spectra import Archive
from tests.fixtures import OnePass, card, header, numeric_card, primary, document


def table_bytes(columns, rows, heap=b"", gap=b"", *, theap=None, pcount=None):
    """Small specimens only. Variable cell input is (count, heap_offset)."""
    width = sum((8 if c["kind"] == "P" else 16) if "kind" in c
                else 4 * c.get("repeat", 1) for c in columns)
    row_bytes = bytearray()
    for row in rows:
        if len(row) != len(columns):
            raise ValueError("specimen row width")
        for c, cell in zip(columns, row):
            size = (4 if c["kind"] == "P" else 8) if "kind" in c else 4
            for value in cell:
                row_bytes.extend(value.to_bytes(size, "big", signed=True))
    if len(row_bytes) != width * len(rows):
        raise ValueError("specimen cell width")
    fields = [
        card("XTENSION", "BINTABLE"), card("BITPIX", 8), card("NAXIS", 2),
        card("NAXIS1", width), card("NAXIS2", len(rows)),
        card("PCOUNT", len(gap) + len(heap) if pcount is None else pcount),
        card("GCOUNT", 1), card("TFIELDS", len(columns)),
        card("THEAP", len(row_bytes) + len(gap) if theap is None else theap),
    ]
    for i, c in enumerate(columns, 1):
        suffix = str(i)
        form = "1" + c["kind"] + "J" if "kind" in c else str(c.get("repeat", 1)) + "J"
        fields.extend([card("TTYPE" + suffix, c["name"]), card("TFORM" + suffix, form)])
        if "null" in c:
            fields.append(card("TNULL" + suffix, c["null"]))
        for option, prefix in (("scale", "TSCAL"), ("zero", "TZERO")):
            if option in c:
                fields.append(numeric_card(prefix + suffix, c[option]))
    data = bytes(row_bytes) + gap + heap
    return header(fields) + data + b"\0" * (-len(data) % 2880)


def small_case(kind):
    heap = b"".join(x.to_bytes(4, "big", signed=True) for x in (10, -999, 30))
    columns = [
        {"name": "quality"},
        {"name": "flux", "kind": kind, "null": -999, "scale": "0.5", "zero": "1"},
        {"name": "other", "kind": kind, "null": 10, "scale": "-2"},
    ]
    rows = [([2], (3, 0), (2, 4)), ([5], (2, 4), (1, 1)),
            ([7], (0, -123), (0, -1))]
    expected = {}
    for ri, row in enumerate(rows):
        for c, cell in zip(columns, row):
            if "kind" in c:
                count, offset = cell
                values = [int.from_bytes(heap[offset + 4*i:offset + 4*i + 4],
                                         "big", signed=True) for i in range(count)]
            else:
                values = cell
            scale, zero = Fraction(c.get("scale", "1")), Fraction(c.get("zero", "0"))
            expected[ri, c["name"]] = tuple(
                None if x == c.get("null") else x * scale + zero for x in values)
    return primary() + table_bytes(columns, rows, heap, b"gap!?"), expected


def check_cells(archive, revision, expected, hdu=1):
    for (row, name), values in expected.items():
        for start, stop in ((0, 99), (0, 0), (1, 2), (2, 9), (99, 100)):
            actual = archive.cell(revision, row, (hdu, name), start, stop)
            assert actual == values[start:stop], (row, name, start, stop, actual, values)


def fixture_check():
    for kind in ("P", "Q"):
        data, expected = small_case(kind)
        assert len(data) % 2880 == 0
        assert expected[0, "flux"] == (Fraction(6), None, Fraction(16))
        assert expected[1, "flux"] == (None, Fraction(16))
        assert expected[0, "other"] == (Fraction(1998), Fraction(-60))
        assert expected[1, "other"] == (Fraction(-5630),)
        assert expected[2, "flux"] == expected[2, "other"] == ()
        assert b"gap!?" in data
        source = OnePass(data, (1, 7, 79, 8192))
        assert b"".join(source) == data and source.iterations == 1
    for kind, size in (("P", 8), ("Q", 16)):
        generated = b"".join(large_source(kind, 3, 2))
        direct = primary() + table_bytes([{"name": "flux", "kind": kind}],
                                         [((3, 0),), ((3, 0),)], b"\0\0\0\7" * 3)
        # large_source omits THEAP (default row end); compare its data region.
        assert generated[5760:] == direct[5760:]
        assert generated[5760:5760 + size] == (3).to_bytes(size // 2, "big", signed=True) + bytes(size // 2)
    print("HEAP_FIXTURES_OK: P/Q, overlap, column interpretation, unaligned bytes, empty offsets")


def verify():
    fixture_check()
    with tempfile.TemporaryDirectory(prefix="spectra-heap-") as directory:
        root = Path(directory)
        path = root / "archive.sqlite"
        archive = Archive(path)
        try:
            old = archive.ingest(OnePass(document()))
            original = archive.describe(old)
            saved = []
            for kind in ("P", "Q"):
                data, expected = small_case(kind)
                source_path = root / "source.fits"
                source_path.write_bytes(data)
                with source_path.open("rb") as stream:
                    revision = archive.ingest(iter(lambda: stream.read(83), b""))
                source_path.unlink()
                check_cells(archive, revision, expected)
                metadata = archive.describe(revision)
                variable = metadata["tables"][0]["columns"][1]
                assert variable["tform"] == "1" + kind + "J" and variable["repeat"] == 1
                assert archive.select_rows(revision, "quality", 2, 5) == (0, 1)
                try:
                    archive.select_rows(revision, "flux", 0, 99)
                except ValueError:
                    pass
                else:
                    raise AssertionError("variable column accepted for scalar selection")
                saved.append((revision, expected, metadata))
            # Multiple HDUs keep heap offsets local.
            p, pe = small_case("P")
            q, qe = small_case("Q")
            multi = archive.ingest(OnePass(p + q[2880:], (1, 81, 4097)))
            check_cells(archive, multi, pe, 1)
            check_cells(archive, multi, qe, 2)
            before = tuple(archive._connection.execute("SELECT * FROM revisions ORDER BY revision"))
            def unchanged():
                assert tuple(archive._connection.execute("SELECT * FROM revisions ORDER BY revision")) == before
                assert archive.describe(old) == original
                assert not archive._connection.in_transaction
                for rev, exp, meta in saved:
                    assert archive.describe(rev) == meta
                    check_cells(archive, rev, exp)
            for kind in ("P", "Q"):
                c = [{"name": "flux", "kind": kind}]
                for descriptor in ((-1, 0), (4, 0), (1, -1), (1, 10)):
                    bad = primary() + table_bytes(c, [((1, 0),), (descriptor,)], bytes(12))
                    try:
                        archive.ingest(OnePass(bad))
                    except ValueError:
                        pass
                    else:
                        raise AssertionError(("accepted invalid descriptor", descriptor))
                    unchanged()
                good, _ = small_case(kind)
                for bad in (good[:-1], good[:-1] + b"x", good + b"x",
                            primary() + table_bytes(c, [((1, 0),)], bytes(4), theap=0),
                            primary() + table_bytes(c, [((1, 0),)], bytes(4), theap=999)):
                    try:
                        archive.ingest(OnePass(bad))
                    except ValueError:
                        pass
                    else:
                        raise AssertionError("accepted malformed input")
                    unchanged()
                error = LookupError("source failed at EOF")
                def broken():
                    yield good
                    raise error
                try:
                    archive.ingest(broken())
                except LookupError as caught:
                    assert caught is error
                else:
                    raise AssertionError("source failure lost")
                unchanged()
            archive.close()
            archive = Archive(path)
            assert archive.describe(old) == original
            for rev, exp, meta in saved:
                assert archive.describe(rev) == meta
                check_cells(archive, rev, exp)
            new = archive.ingest(OnePass(document()))
            assert new != old
            for rev, exp, meta in saved:
                check_cells(archive, rev, exp)
            print("HEAP_INTEGRATION_OK: import, failure, source removal, reopen, append")
        finally:
            archive.close()


def large_source(kind, elements, rows):
    size = 4 if kind == "P" else 8
    width = 2 * size
    if not 0 <= elements < (1 << (8 * size - 1)) or rows < 1:
        raise ValueError("specimen size")
    yield primary()
    yield header([
        card("XTENSION", "BINTABLE"), card("BITPIX", 8), card("NAXIS", 2),
        card("NAXIS1", width), card("NAXIS2", rows), card("PCOUNT", 4 * elements),
        card("GCOUNT", 1), card("TFIELDS", 1),
        card("TTYPE1", "flux"), card("TFORM1", "1" + kind + "J"),
    ])
    descriptor = elements.to_bytes(size, "big", signed=True) + bytes(size)
    left = rows
    while left:
        n = min(left, 65536 // width)
        yield descriptor * n
        left -= n
    left = elements
    while left:
        n = min(left, 16384)
        yield b"\0\0\0\7" * n
        left -= n
    yield bytes(-(width * rows + 4 * elements) % 2880)


def resource_check(kind, elements, rows):
    with tempfile.TemporaryDirectory(prefix="spectra-heap-resource-") as directory:
        archive = Archive(Path(directory) / "archive.sqlite")
        try:
            tracemalloc.start()
            revision = archive.ingest(large_source(kind, elements, rows))
            _, import_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            tracemalloc.start()
            start = max(0, elements - 2)
            result = archive.cell(revision, rows - 1, "flux", start, elements)
            _, read_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            assert result == (Fraction(7),) * (elements - start)
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            print(json.dumps({"kind": kind, "elements": elements, "rows": rows,
                              "import_python_peak_bytes": import_peak,
                              "slice_python_peak_bytes": read_peak,
                              "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024}))
        finally:
            if tracemalloc.is_tracing():
                tracemalloc.stop()
            archive.close()


def demo():
    with tempfile.TemporaryDirectory(prefix="spectra-heap-demo-") as directory:
        path = Path(directory) / "archive.sqlite"
        archive = Archive(path)
        try:
            data, expected = small_case("Q")
            revision = archive.ingest(OnePass(data))
            check_cells(archive, revision, expected)
            archive.close()
            archive = Archive(path)
            print("reopened revision:", revision)
            print("overlapping flux:", archive.cell(revision, 0, "flux", 0, 3),
                  archive.cell(revision, 1, "flux", 0, 3))
            print("unaligned, different interpretation:", archive.cell(revision, 1, "other", 0, 1))
            print("empty, ignored negative offset:", archive.cell(revision, 2, "flux", 0, 3))
        finally:
            archive.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fixtures", "verify", "demo", "resource"))
    parser.add_argument("--kind", choices=("P", "Q"), default="Q")
    parser.add_argument("--elements", type=int, default=4194304)
    parser.add_argument("--rows", type=int, default=256)
    args = parser.parse_args()
    if args.mode == "fixtures":
        fixture_check()
    elif args.mode == "verify":
        verify()
    elif args.mode == "demo":
        demo()
    else:
        resource_check(args.kind, args.elements, args.rows)


if __name__ == "__main__":
    main()
