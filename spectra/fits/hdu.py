from dataclasses import dataclass

from spectra.fits.headers import read_header
from spectra.fits.layout import build_primary_layout, build_table_layout
from spectra.fits.padding import read_data_padding


@dataclass(frozen=True)
class HDUScanResult:
    table_count: int
    row_count: int
    cell_count: int
    input_bytes: int


def scan_hdus(reader, on_table, on_row, on_heap):
    """Single-pass scan. Row areas arrive whole (their width is bounded by the
    column declarations); gap bytes are discarded and heap bytes are streamed
    to on_heap in input-block-sized pieces so no heap is materialized."""
    primary = build_primary_layout(read_header(reader))
    read_data_padding(reader, primary.data_size)
    hdu_index = 1
    table_count = row_count = cell_count = 0
    while reader.peek_byte() is not None:
        layout = build_table_layout(read_header(reader), hdu_index)
        on_table(layout)
        for row in range(layout.row_count):
            payload = reader.read_exact(layout.row_width)
            on_row(layout, row, payload)
            row_count += 1
            cell_count += len(layout.columns)
        for _ in reader.iter_exact(layout.gap_size):
            pass
        streamed = 0
        for piece in reader.iter_exact(layout.heap_length):
            on_heap(layout, streamed, piece)
            streamed += len(piece)
        if streamed != layout.heap_length:
            raise ValueError("heap stream length mismatch")
        read_data_padding(reader, layout.data_size)
        table_count += 1
        hdu_index += 1
    reader.require_eof()
    if not table_count:
        raise ValueError("at least one BINTABLE is required")
    return HDUScanResult(table_count, row_count, cell_count, reader.position)
