from fractions import Fraction

from spectra.access.locators import resolve_column
from spectra.storage.fixed_cells import FixedCellStore
from spectra.storage.codec import decode_j_values
from spectra.columns.fixed import interpret_fixed_values


def select_rows(connection, revision, column, lower, upper):
    target = resolve_column(connection, revision, column)
    if target.column.kind.is_variable:
        raise ValueError("row selection requires a fixed scalar column")
    if target.column.repeat != 1:
        raise ValueError("row selection requires a scalar column")
    if any(isinstance(value, bool) or not isinstance(value, (int, Fraction))
           for value in (lower, upper)):
        raise ValueError("selection bounds must be exact numbers")
    if lower > upper:
        raise ValueError("selection bounds are reversed")
    store = FixedCellStore(connection)
    selected = []
    for row in range(target.row_count):
        raw = store.read_slice(revision, target.hdu_index, row, target.ordinal, 1, 0, 1)
        value = interpret_fixed_values(decode_j_values(raw), target.column)[0]
        if value is not None and lower <= value <= upper:
            selected.append(row)
    return tuple(selected)
