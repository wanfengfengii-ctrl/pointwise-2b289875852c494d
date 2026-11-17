"""Archive-owned variable-array storage.

Import side: the scanner hands validated P/Q descriptors and streamed heap
pieces to this store inside the import transaction; rollback removes every
candidate-owned byte. Read side: a resolved descriptor plus its table's
durable heap extent locate a bounded window, fetched chunk by chunk, after
the source iterator, the caller's file and the importing Archive are gone.
"""
from spectra.columns.variable import decode_descriptor, validate_descriptor_range

HEAP_CHUNK_SIZE = 1 << 20


class VariableStore:
    def __init__(self, connection):
        self.connection = connection
        self._active = None
        self._pending = bytearray()
        self._received = 0
        self._chunk_index = 0

    # ---- import side (requires the import transaction) ----

    def begin_table(self, revision, layout):
        if not self.connection.in_transaction:
            raise RuntimeError("heap writes require an import transaction")
        if self._active is not None:
            raise RuntimeError("previous table heap is unfinished")
        if not layout.has_variable:
            return
        self.connection.execute(
            "INSERT INTO heaps(revision,hdu_index,heap_length) VALUES (?,?,?)",
            (revision, layout.hdu_index, layout.heap_length),
        )
        self._active = (revision, layout.hdu_index, layout.heap_length)
        self._pending = bytearray()
        self._received = 0
        self._chunk_index = 0

    def write_descriptor(self, revision, layout, row, placement, payload):
        if not self.connection.in_transaction:
            raise RuntimeError("descriptor writes require an import transaction")
        if type(row) is not int or not 0 <= row < layout.row_count:
            raise ValueError("invalid staged row")
        count, offset = decode_descriptor(placement.column.kind, payload)
        validate_descriptor_range(count, offset, layout.heap_length)
        self.connection.execute(
            "INSERT INTO variable_descriptors(revision,hdu_index,row_index,"
            "ordinal,element_count,heap_offset) VALUES (?,?,?,?,?,?)",
            (revision, layout.hdu_index, row, placement.ordinal, count, offset),
        )

    def write_heap(self, revision, layout, offset, data):
        if self._active is None or self._active[:2] != (revision, layout.hdu_index):
            raise ValueError("heap chunk without an active variable table")
        if offset != self._received:
            raise ValueError("heap stream out of order")
        view = memoryview(data)
        position = 0
        while position < len(view):
            space = HEAP_CHUNK_SIZE - len(self._pending)
            take = min(space, len(view) - position)
            self._pending += view[position:position + take]
            position += take
            if len(self._pending) == HEAP_CHUNK_SIZE:
                self._flush()
        self._received += len(data)
        if self._received > self._active[2]:
            raise ValueError("heap stream exceeds declared heap")

    def finish_table(self, revision, layout):
        if not layout.has_variable:
            if self._active is not None:
                raise ValueError("heap writer leaked onto a fixed table")
            return
        if self._active is None:
            raise ValueError("variable table is missing its heap writer")
        active_revision, hdu_index, heap_length = self._active
        if (active_revision, hdu_index) != (revision, layout.hdu_index):
            raise ValueError("heap writer belongs to another table")
        if self._received != heap_length:
            raise ValueError("streamed heap length disagrees with the header")
        if self._pending:
            self._flush()
        record = self.connection.execute(
            "SELECT count(*),coalesce(sum(length(payload)),0) FROM heap_chunks "
            "WHERE revision=? AND hdu_index=?",
            (revision, hdu_index),
        ).fetchone()
        expected_chunks = -(-heap_length // HEAP_CHUNK_SIZE)
        if tuple(record) != (expected_chunks, heap_length):
            raise ValueError("stored heap disagrees with the header")
        self._active = None

    def _flush(self):
        revision, hdu_index, _ = self._active
        self.connection.execute(
            "INSERT INTO heap_chunks(revision,hdu_index,chunk_index,payload) "
            "VALUES (?,?,?,?)",
            (revision, hdu_index, self._chunk_index, memoryview(self._pending)),
        )
        self._chunk_index += 1
        self._pending.clear()

    def count_for_revision(self, revision):
        return self.connection.execute(
            "SELECT count(*) FROM variable_descriptors WHERE revision=?", (revision,)
        ).fetchone()[0]

    def verify_table(self, revision, layout):
        variable_ordinals = tuple(
            placement.ordinal for placement in layout.columns
            if placement.column.kind.is_variable
        )
        if not variable_ordinals:
            if self.connection.execute(
                "SELECT count(*) FROM variable_descriptors WHERE revision=? "
                "AND hdu_index=?", (revision, layout.hdu_index)
            ).fetchone()[0]:
                raise ValueError("unexpected staged descriptor")
            return
        record = self.connection.execute(
            "SELECT heap_length FROM heaps WHERE revision=? AND hdu_index=?",
            (revision, layout.hdu_index),
        ).fetchone()
        if record is None or record[0] != layout.heap_length:
            raise ValueError("stored heap extent disagrees")
        heap_length = record[0]
        records = self.connection.execute(
            "SELECT ordinal,count(*),min(row_index),max(row_index) "
            "FROM variable_descriptors WHERE revision=? AND hdu_index=? "
            "GROUP BY ordinal ORDER BY ordinal",
            (revision, layout.hdu_index),
        )
        seen = 0
        for ordinal, count, first, last in records:
            if ordinal not in variable_ordinals:
                raise ValueError("unexpected staged variable column")
            if (count != layout.row_count or first != 0
                    or last != layout.row_count - 1):
                raise ValueError("incomplete staged variable column")
            seen += 1
        if seen != (len(variable_ordinals) if layout.row_count else 0):
            raise ValueError("missing staged variable column")
        # Re-check every stored referenced range before publication, even
        # ranges that are never read.
        bad = self.connection.execute(
            "SELECT count(*) FROM variable_descriptors WHERE revision=? "
            "AND hdu_index=? AND (element_count < 0 OR (element_count > 0 AND "
            "(heap_offset < 0 OR heap_offset + 4*element_count > ?)))",
            (revision, layout.hdu_index, heap_length),
        ).fetchone()[0]
        if bad:
            raise ValueError("stored descriptor range beyond the heap")

    # ---- read side (published revisions only; no source is consulted) ----

    def read_descriptor(self, revision, hdu_index, row, ordinal):
        record = self.connection.execute(
            "SELECT element_count,heap_offset FROM variable_descriptors "
            "WHERE revision=? AND hdu_index=? AND row_index=? AND ordinal=?",
            (revision, hdu_index, row, ordinal),
        ).fetchone()
        if record is None:
            raise KeyError((revision, hdu_index, row, ordinal))
        return record[0], record[1]

    def read_heap_slice(self, revision, hdu_index, start, stop):
        if type(start) is not int or type(stop) is not int or start > stop:
            raise ValueError("invalid heap window")
        if start == stop:
            return b""
        if start < 0:
            raise ValueError("invalid heap window")
        record = self.connection.execute(
            "SELECT heap_length FROM heaps WHERE revision=? AND hdu_index=?",
            (revision, hdu_index),
        ).fetchone()
        if record is None:
            raise ValueError("stored heap extent is missing")
        heap_length = record[0]
        if stop > heap_length:
            raise ValueError("heap window beyond the stored heap")
        pieces = []
        position = start
        while position < stop:
            chunk_index, inner = divmod(position, HEAP_CHUNK_SIZE)
            take = min(HEAP_CHUNK_SIZE - inner, stop - position)
            record = self.connection.execute(
                "SELECT length(payload),substr(payload,?,?) FROM heap_chunks "
                "WHERE revision=? AND hdu_index=? AND chunk_index=?",
                (inner + 1, take, revision, hdu_index, chunk_index),
            ).fetchone()
            if record is None:
                raise ValueError("stored heap chunk is missing")
            stored, piece = record
            if stored != min(HEAP_CHUNK_SIZE, heap_length - chunk_index * HEAP_CHUNK_SIZE):
                raise ValueError("stored heap chunk length mismatch")
            if len(piece) != take:
                raise ValueError("stored heap slice mismatch")
            pieces.append(piece)
            position += take
        return b"".join(pieces)
