from spectra.access.locators import resolve_column, validate_row_index
from spectra.storage.slices import normalize_slice
from spectra.storage.fixed_cells import FixedCellStore
from spectra.storage.codec import decode_j_values
from spectra.columns.fixed import interpret_fixed_values


def read_cell(connection, revision, row, column, start, stop):
    target = resolve_column(connection, revision, column)
    validate_row_index(target, row)
    window = normalize_slice(target.column.repeat, start, stop)
    payload = FixedCellStore(connection).read_slice(
        revision, target.hdu_index, row, target.ordinal, target.column.repeat,
        window.start, window.stop,
    )
    return interpret_fixed_values(decode_j_values(payload), target.column)
