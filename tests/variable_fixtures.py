"""Independent V2 specimens: byte builder, expected-value calculator, big
generated sources and a full seven-table snapshot. These helpers recompute
expectations straight from the specimen bytes and never call archive code."""
from fractions import Fraction

from tests.fixtures import card, numeric_card, header, primary


def vtable(columns, rows, heap=b"", gap=b"", *, theap=None, pcount=None,
           omit_theap=False, extra=()):
    """Build one BINTABLE HDU. Variable columns set kind to "P"/"Q" and their
    row cells are (count, heap_offset); fixed cells are lists of J values."""
    width = 0
    for column in columns:
        if "kind" in column:
            width += 8 if column["kind"] == "P" else 16
        else:
            width += 4 * column.get("repeat", 1)
    row_bytes = bytearray()
    for row in rows:
        if len(row) != len(columns):
            raise ValueError("specimen row width")
        for column, cell in zip(columns, row):
            if "kind" in column:
                size = 4 if column["kind"] == "P" else 8
                count, offset = cell
                row_bytes += count.to_bytes(size, "big", signed=True)
                row_bytes += offset.to_bytes(size, "big", signed=True)
            else:
                if len(cell) != column.get("repeat", 1):
                    raise ValueError("specimen cell width")
                for value in cell:
                    row_bytes += value.to_bytes(4, "big", signed=True)
    if len(row_bytes) != width * len(rows):
        raise ValueError("specimen layout")
    fields = [
        card("XTENSION", "BINTABLE"), card("BITPIX", 8), card("NAXIS", 2),
        card("NAXIS1", width), card("NAXIS2", len(rows)),
        card("PCOUNT", len(gap) + len(heap) if pcount is None else pcount),
        card("GCOUNT", 1), card("TFIELDS", len(columns)),
    ]
    if not omit_theap:
        fields.append(card("THEAP", len(row_bytes) + len(gap) if theap is None else theap))
    for index, column in enumerate(columns, 1):
        suffix = str(index)
        form = column.get("tform") or (
            "1" + column["kind"] + "J" if "kind" in column
            else str(column.get("repeat", 1)) + "J")
        fields.extend([card("TTYPE" + suffix, column["name"]),
                       card("TFORM" + suffix, form)])
        if "null" in column:
            fields.append(card("TNULL" + suffix, column["null"]))
        for option, prefix in (("scale", "TSCAL"), ("zero", "TZERO")):
            if option in column:
                fields.append(numeric_card(prefix + suffix, column[option]))
    fields.extend(extra)
    data = bytes(row_bytes) + gap + heap
    return header(fields) + data + b"\0" * (-len(data) % 2880)


def heap_j_values(heap, offset, count):
    return [int.from_bytes(heap[offset + 4 * i: offset + 4 * i + 4], "big", signed=True)
            for i in range(count)]


def _fraction(token):
    if isinstance(token, str):
        token = token.replace("D", "E").replace("d", "e")
    return Fraction(token)


def expect_cell(column, cell, heap):
    """Independent physical value for one cell: raw null check first, then
    exact scaling, empty arrays ignore their offset."""
    if "kind" in column:
        count, offset = cell
        raw = heap_j_values(heap, offset, count) if count > 0 else []
    else:
        raw = list(cell)
    scale = _fraction(column.get("scale", "1"))
    zero = _fraction(column.get("zero", "0"))
    null = column.get("null")
    return tuple(
        None if null is not None and value == null else value * scale + zero
        for value in raw
    )


def expect_table(columns, rows, heap):
    return {(row_index, column["name"]): expect_cell(column, cell, heap)
            for row_index, row in enumerate(rows)
            for column, cell in zip(columns, row)}


def big_source(kind, elements, rows):
    """Generated large source: one variable column, every row's descriptor
    references the whole heap of `elements` J values, all equal to 7."""
    size = 4 if kind == "P" else 8
    width = 2 * size
    if not 0 <= elements < (1 << (8 * size - 1)) or rows < 1:
        raise ValueError("specimen size")
    yield primary()
    yield header([
        card("XTENSION", "BINTABLE"), card("BITPIX", 8), card("NAXIS", 2),
        card("NAXIS1", width), card("NAXIS2", rows), card("PCOUNT", 4 * elements),
        card("GCOUNT", 1), card("TFIELDS", 1),
        card("TTYPE1", "flux"), card("TFORM1", "1" + kind + "J"),
    ])
    descriptor = elements.to_bytes(size, "big", signed=True) + bytes(size)
    left = rows
    while left:
        count = min(left, 65536 // width)
        yield descriptor * count
        left -= count
    left = elements
    while left:
        count = min(left, 16384)
        yield b"\0\0\0\7" * count
        left -= count
    yield bytes(-(width * rows + 4 * elements) % 2880)


def full_snapshot(connection):
    names = ("revisions", "tables", "columns", "fixed_cells",
             "variable_descriptors", "heaps", "heap_chunks")
    return {name: tuple(connection.execute("SELECT * FROM " + name + " ORDER BY 1,2,3"))
            for name in names}
