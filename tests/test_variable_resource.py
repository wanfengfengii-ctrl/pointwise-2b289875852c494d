"""Generated-source resource checks: import/slice working memory must stay
bounded while variable element count, heap bytes and row count grow. Bounds
are generous constants, not throughput targets; heap_cases.py resource
reports the authoritative per-process numbers."""
import tracemalloc
import unittest
from fractions import Fraction

from spectra import Archive
from tests.variable_fixtures import big_source


def ingest_measured(elements, rows):
    archive = Archive(":memory:")
    try:
        tracemalloc.start()
        try:
            revision = archive.ingest(big_source("Q", elements, rows))
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        return archive, revision, peak
    except BaseException:
        archive.close()
        raise


def read_measured(archive, revision, row, start, stop):
    tracemalloc.start()
    try:
        result = archive.cell(revision, row, "flux", start, stop)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    return result, peak


class TestVariableResource(unittest.TestCase):
    def test_import_peak_flat_in_element_count(self):
        small_archive, small_revision, small_peak = ingest_measured(1024, 64)
        self.addCleanup(small_archive.close)
        large_archive, large_revision, large_peak = ingest_measured(262144, 64)
        self.addCleanup(large_archive.close)
        # 256x the heap bytes: the peak may only move by chunking constants.
        self.assertLess(large_peak, small_peak + 4 * (1 << 20))
        self.assertLess(large_peak, 8 * (1 << 20))
        self.assertEqual(large_archive.cell(large_revision, 63, "flux", 0, 2),
                         (Fraction(7), Fraction(7)))
        self.assertEqual(small_archive.cell(small_revision, 0, "flux", 0, 2),
                         (Fraction(7), Fraction(7)))

    def test_import_peak_flat_in_row_count(self):
        small_archive, _, small_peak = ingest_measured(4, 64)
        self.addCleanup(small_archive.close)
        large_archive, large_revision, large_peak = ingest_measured(4, 16384)
        self.addCleanup(large_archive.close)
        # 256x the rows: no per-row retention may accumulate.
        self.assertLess(large_peak, 4 * small_peak + (1 << 20))
        self.assertLess(large_peak, 4 * (1 << 20))
        self.assertEqual(large_archive.cell(large_revision, 16383, "flux", 0, 4),
                         (Fraction(7),) * 4)

    def test_small_slice_from_large_cell(self):
        elements = 1 << 20
        archive, revision, _ = ingest_measured(elements, 32)
        self.addCleanup(archive.close)
        result, peak = read_measured(archive, revision, 31, elements - 2, elements)
        self.assertEqual(result, (Fraction(7), Fraction(7)))
        # A two-element window never decodes the million-element cell.
        self.assertLess(peak, 2 * (1 << 20))
