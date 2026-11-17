from dataclasses import dataclass

from spectra.fits.headers import read_header
from spectra.fits.layout import build_primary_layout, build_fixed_layout
from spectra.fits.padding import read_data_padding


@dataclass(frozen=True)
class HDUScanResult:
    table_count: int
    row_count: int
    cell_count: int
    input_bytes: int


def scan_fixed_hdus(reader, on_table, on_row):
    primary = build_primary_layout(read_header(reader))
    read_data_padding(reader, primary.data_size)
    hdu_index = 1
    table_count = row_count = cell_count = 0
    while reader.peek_byte() is not None:
        layout = build_fixed_layout(read_header(reader), hdu_index)
        on_table(layout)
        for row in range(layout.row_count):
            payload = reader.read_exact(layout.row_width)
            on_row(layout, row, payload)
            row_count += 1
            cell_count += len(layout.columns)
        read_data_padding(reader, layout.data_size)
        table_count += 1
        hdu_index += 1
    reader.require_eof()
    if not table_count:
        raise ValueError("at least one BINTABLE is required")
    return HDUScanResult(table_count, row_count, cell_count, reader.position)
