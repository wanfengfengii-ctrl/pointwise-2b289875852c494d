from dataclasses import dataclass

from spectra.catalog.revisions import require_published_revision
from spectra.catalog.tables import load_column
from spectra.columns.fixed import FixedColumn


@dataclass(frozen=True)
class ColumnTarget:
    revision: int
    hdu_index: int
    row_count: int
    ordinal: int
    column: FixedColumn


def resolve_column(connection, revision, column):
    require_published_revision(connection, revision)
    parameters = [revision]
    where = "c.revision=?"
    if isinstance(column, str) and column:
        where += " AND c.name=?"
        parameters.append(column)
    elif (isinstance(column, tuple) and len(column) == 2
          and type(column[0]) is int and column[0] >= 1
          and isinstance(column[1], str) and column[1]):
        where += " AND c.hdu_index=? AND c.name=?"
        parameters.extend(column)
    else:
        raise KeyError(column)
    records = connection.execute(
        "SELECT c.hdu_index,t.row_count,c.ordinal FROM columns c JOIN tables t "
        "ON c.revision=t.revision AND c.hdu_index=t.hdu_index WHERE " + where + " LIMIT 2",
        parameters,
    ).fetchall()
    if len(records) != 1:
        raise KeyError(column)
    hdu, rows, ordinal = records[0]
    interpretation = load_column(connection, revision, hdu, ordinal)
    return ColumnTarget(revision, hdu, rows, ordinal, interpretation)


def validate_row_index(target, row):
    if type(row) is not int or row < 0:
        raise ValueError("row must be a nonnegative integer")
    if row >= target.row_count:
        raise KeyError(row)
    return row
