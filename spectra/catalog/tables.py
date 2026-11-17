from fractions import Fraction

from spectra.columns.fixed import FixedColumn
from spectra.columns.types import FixedJType, VariableJType
from spectra.columns.scaling import Scaling


def _kind_code(kind):
    return kind.letter if kind.is_variable else "fixed"


def stage_table(session, layout):
    session.require_staging()
    connection = session.connection
    connection.execute(
        "INSERT INTO tables(revision,hdu_index,row_count,row_width,column_count) "
        "VALUES (?,?,?,?,?)",
        (session.revision, layout.hdu_index, layout.row_count, layout.row_width,
         len(layout.columns)),
    )
    for placement in layout.columns:
        column = placement.column
        scale, zero = column.scaling.scale, column.scaling.zero
        connection.execute(
            "INSERT INTO columns(revision,hdu_index,ordinal,name,repeat,tnull,"
            "scale_num,scale_den,zero_num,zero_den,kind) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (session.revision, layout.hdu_index, placement.ordinal, column.name,
             column.repeat, column.tnull, str(scale.numerator), str(scale.denominator),
             str(zero.numerator), str(zero.denominator), _kind_code(column.kind)),
        )


def _column(record):
    ordinal, name, repeat, tnull, sn, sd, zn, zd, code = record
    if code == "fixed":
        kind = FixedJType(repeat)
    elif code in ("P", "Q"):
        if repeat != 1:
            raise ValueError("stored variable descriptor repeat corrupted")
        kind = VariableJType(code)
    else:
        raise ValueError("unknown stored column kind")
    return ordinal, FixedColumn(
        name, kind, tnull,
        Scaling(Fraction(int(sn), int(sd)), Fraction(int(zn), int(zd))),
    )


_COLUMN_FIELDS = "ordinal,name,repeat,tnull,scale_num,scale_den,zero_num,zero_den,kind"


def load_column(connection, revision, hdu_index, ordinal):
    record = connection.execute(
        "SELECT " + _COLUMN_FIELDS + " FROM columns "
        "WHERE revision=? AND hdu_index=? AND ordinal=?",
        (revision, hdu_index, ordinal),
    ).fetchone()
    if record is None:
        raise KeyError((revision, hdu_index, ordinal))
    return _column(record)[1]


def load_catalog(connection, revision):
    tables = []
    for hdu, rows in connection.execute(
        "SELECT hdu_index,row_count FROM tables WHERE revision=? ORDER BY hdu_index",
        (revision,),
    ):
        columns = []
        for record in connection.execute(
            "SELECT " + _COLUMN_FIELDS + " FROM columns "
            "WHERE revision=? AND hdu_index=? ORDER BY ordinal",
            (revision, hdu),
        ):
            ordinal, column = _column(record)
            columns.append((ordinal, column))
        tables.append((hdu, rows, tuple(columns)))
    return tuple(tables)
