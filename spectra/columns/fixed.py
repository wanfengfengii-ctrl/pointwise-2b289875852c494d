from dataclasses import dataclass

from spectra.columns.types import parse_column_tform
from spectra.columns.nulls import parse_tnull, is_raw_null
from spectra.columns.scaling import parse_scaling, apply_scaling, Scaling
from spectra.fits.headers import require_keyword


@dataclass(frozen=True)
class FixedColumn:
    # Column declaration shared by fixed and variable columns; kind decides
    # whether cells are inline J values or P/Q heap descriptors.
    name: str
    kind: object
    tnull: int | None
    scaling: Scaling

    @property
    def repeat(self):
        return self.kind.repeat


def parse_column(header, index):
    suffix = str(index)
    name = require_keyword(header, "TTYPE" + suffix)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("column name must be nonempty")
    kind = parse_column_tform(require_keyword(header, "TFORM" + suffix))
    tnull = parse_tnull(header.get("TNULL" + suffix))
    scaling = parse_scaling(
        header.lexical("TSCAL" + suffix, "1"),
        header.lexical("TZERO" + suffix, "0"),
    )
    return FixedColumn(name, kind, tnull, scaling)


def interpret_fixed_values(raw_values, column):
    return tuple(
        None if is_raw_null(raw, column.tnull)
        else apply_scaling(raw, column.scaling)
        for raw in raw_values
    )
