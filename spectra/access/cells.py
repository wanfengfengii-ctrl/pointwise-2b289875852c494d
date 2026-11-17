from spectra.access.locators import resolve_column, validate_row_index
from spectra.storage.slices import normalize_slice
from spectra.storage.fixed_cells import FixedCellStore
from spectra.storage.variable_cells import VariableStore
from spectra.storage.codec import decode_j_values
from spectra.columns.fixed import interpret_fixed_values


def read_cell(connection, revision, row, column, start, stop):
    target = resolve_column(connection, revision, column)
    validate_row_index(target, row)
    kind = target.column.kind
    if kind.is_variable:
        store = VariableStore(connection)
        count, offset = store.read_descriptor(
            revision, target.hdu_index, row, target.ordinal)
        window = normalize_slice(count, start, stop)
        payload = store.read_heap_slice(
            revision, target.hdu_index,
            offset + window.byte_start, offset + window.byte_stop)
        return interpret_fixed_values(decode_j_values(payload), target.column)
    window = normalize_slice(kind.repeat, start, stop)
    payload = FixedCellStore(connection).read_slice(
        revision, target.hdu_index, row, target.ordinal, kind.repeat,
        window.start, window.stop,
    )
    return interpret_fixed_values(decode_j_values(payload), target.column)
