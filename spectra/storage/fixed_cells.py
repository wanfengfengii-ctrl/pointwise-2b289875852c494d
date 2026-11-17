from spectra.storage.codec import validate_fixed_payload
from spectra.storage.slices import normalize_slice


class FixedCellStore:
    def __init__(self, connection):
        self.connection = connection

    def write(self, revision, layout, row, placement, payload):
        if not self.connection.in_transaction:
            raise RuntimeError("cell writes require an import transaction")
        if type(row) is not int or not 0 <= row < layout.row_count:
            raise ValueError("invalid staged row")
        validate_fixed_payload(payload, placement.column.repeat)
        self.connection.execute(
            "INSERT INTO fixed_cells(revision,hdu_index,row_index,ordinal,payload) "
            "VALUES (?,?,?,?,?)",
            (revision, layout.hdu_index, row, placement.ordinal, payload),
        )

    def read_slice(self, revision, hdu_index, row, ordinal, repeat, start, stop):
        window = normalize_slice(repeat, start, stop)
        record = self.connection.execute(
            "SELECT length(payload),substr(payload,?,?) FROM fixed_cells "
            "WHERE revision=? AND hdu_index=? AND row_index=? AND ordinal=?",
            (window.byte_start + 1, window.byte_count, revision, hdu_index, row, ordinal),
        ).fetchone()
        if record is None:
            raise KeyError((revision, hdu_index, row, ordinal))
        if record[0] != repeat * 4:
            raise ValueError("stored fixed cell length mismatch")
        return record[1]

    def count_for_revision(self, revision):
        return self.connection.execute(
            "SELECT count(*) FROM fixed_cells WHERE revision=?", (revision,)
        ).fetchone()[0]

    def verify_table(self, revision, layout):
        records = self.connection.execute(
            "SELECT ordinal,count(*),min(row_index),max(row_index),"
            "min(length(payload)),max(length(payload)) FROM fixed_cells "
            "WHERE revision=? AND hdu_index=? GROUP BY ordinal ORDER BY ordinal",
            (revision, layout.hdu_index),
        )
        seen = 0
        for record in records:
            ordinal, count, first, last, shortest, longest = record
            if not 0 <= ordinal < len(layout.columns):
                raise ValueError("unexpected staged column")
            placement = layout.columns[ordinal]
            if placement.column.kind.is_variable:
                raise ValueError("variable column staged as fixed")
            width = placement.width
            if (count != layout.row_count or first != 0 or last != layout.row_count - 1
                    or shortest != width or longest != width):
                raise ValueError("incomplete staged fixed column")
            seen += 1
        fixed = sum(1 for placement in layout.columns
                    if not placement.column.kind.is_variable)
        expected = fixed if layout.row_count else 0
        if seen != expected:
            raise ValueError("missing staged fixed column")
