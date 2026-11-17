from fractions import Fraction
from pathlib import Path
import tempfile

from spectra import Archive
from tests.fixtures import document


def main():
    columns = [
        {"name": "temperature", "scale": "-2", "zero": "10", "null": -999},
        {"name": "flux", "repeat": 3, "scale": "0.5", "zero": "1", "null": -999},
    ]
    rows = [([4], [10, -999, 30]), ([2], [40, 50, 60]), ([-999], [70, 80, 90])]
    with tempfile.TemporaryDirectory(prefix="spectra-demo-") as directory:
        root = Path(directory)
        source = root / "observation.fits"
        database = root / "archive.sqlite"
        source.write_bytes(document(columns, rows))
        archive = Archive(database)
        try:
            with source.open("rb") as stream:
                revision = archive.ingest(iter(lambda: stream.read(113), b""))
        finally:
            archive.close()
        source.unlink()
        archive = Archive(database)
        try:
            selected = archive.select_rows(revision, "temperature", Fraction(2), Fraction(6))
            print("revision:", revision)
            print("directory:", archive.describe(revision))
            print("selected rows:", selected)
            for row in selected:
                print("flux window:", row, archive.cell(revision, row, "flux", 0, 3))
            assert selected == (0, 1)
            assert archive.cell(revision, 0, "flux", 0, 3) == (Fraction(6), None, Fraction(16))
        finally:
            archive.close()


if __name__ == "__main__":
    main()
