from itertools import cycle


def card(keyword, value=None):
    if value is None:
        text = keyword
    elif isinstance(value, bool):
        text = f"{keyword:<8}= " + ("T" if value else "F")
    elif isinstance(value, str):
        text = f"{keyword:<8}= '" + value.replace("'", "''") + "'"
    else:
        text = f"{keyword:<8}= {value}"
    if len(text) > 80:
        raise ValueError("test card too long")
    return text.ljust(80).encode("ascii")


def numeric_card(keyword, token):
    return (f"{keyword:<8}= {token}").ljust(80).encode("ascii")


def header(cards):
    raw = b"".join(cards) + card("END")
    return raw + b" " * ((-len(raw)) % 2880)


def primary():
    return header([card("SIMPLE", True), card("BITPIX", 8), card("NAXIS", 0)])


def table(columns, rows, *, overrides=None, extra=()):
    # Column dictionaries contain name, repeat and optional null/scale/zero.
    width = sum(4 * column.get("repeat", 1) for column in columns)
    values = [
        ("XTENSION", "BINTABLE"), ("BITPIX", 8), ("NAXIS", 2),
        ("NAXIS1", width), ("NAXIS2", len(rows)), ("PCOUNT", 0),
        ("GCOUNT", 1), ("TFIELDS", len(columns)),
    ]
    overrides = {} if overrides is None else overrides
    cards = [card(key, overrides.get(key, value)) for key, value in values]
    for index, column in enumerate(columns, 1):
        cards.extend([
            card("TTYPE" + str(index), column["name"]),
            card("TFORM" + str(index), column.get("tform", str(column.get("repeat", 1)) + "J")),
        ])
        if "null" in column:
            cards.append(card("TNULL" + str(index), column["null"]))
        for option, prefix in (("scale", "TSCAL"), ("zero", "TZERO")):
            if option in column:
                cards.append(numeric_card(prefix + str(index), column[option]))
    cards.extend(extra)
    data = bytearray()
    for row in rows:
        if len(row) != len(columns):
            raise ValueError("bad test row")
        for column, values in zip(columns, row):
            if len(values) != column.get("repeat", 1):
                raise ValueError("bad test cell")
            for value in values:
                data.extend(value.to_bytes(4, "big", signed=True))
    return header(cards) + bytes(data) + b"\0" * ((-len(data)) % 2880)


def document(columns=None, rows=None):
    if columns is None:
        columns = [{"name": "quality"}, {"name": "flux", "repeat": 3}]
    if rows is None:
        rows = [([2], [10, -999, 30]), ([5], [40, 50, 60])]
    return primary() + table(columns, rows)


class OnePass:
    def __init__(self, data, sizes=(1, 79, 80, 2881), empty=True):
        self.data = data
        self.sizes = sizes
        self.empty = empty
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        if self.iterations != 1:
            raise AssertionError("source iterated more than once")
        return self._chunks()

    def _chunks(self):
        position = 0
        for size in cycle(self.sizes):
            if position >= len(self.data):
                break
            if self.empty:
                yield b""
            yield self.data[position:position + size]
            position += size


def snapshot(connection):
    result = {}
    for name in ("revisions", "tables", "columns", "fixed_cells"):
        result[name] = tuple(connection.execute("SELECT * FROM " + name + " ORDER BY 1,2,3"))
    return result
