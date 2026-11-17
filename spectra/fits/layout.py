from dataclasses import dataclass
import re

from spectra.fits.headers import require_keyword
from spectra.fits.padding import padding_length
from spectra.columns.fixed import parse_column, FixedColumn


_MAX_SQLITE_INTEGER = (1 << 63) - 1


@dataclass(frozen=True)
class PrimaryLayout:
    data_size: int = 0


@dataclass(frozen=True)
class ColumnPlacement:
    ordinal: int
    offset: int
    column: FixedColumn

    @property
    def width(self):
        return self.column.kind.byte_width


@dataclass(frozen=True)
class TableLayout:
    hdu_index: int
    row_width: int
    row_count: int
    columns: tuple
    pcount: int
    theap: int

    @property
    def row_area_size(self):
        return self.row_width * self.row_count

    @property
    def gap_size(self):
        return self.theap - self.row_area_size

    @property
    def heap_length(self):
        return self.row_area_size + self.pcount - self.theap

    @property
    def data_size(self):
        return self.row_area_size + self.pcount

    @property
    def padding_size(self):
        return padding_length(self.data_size)

    @property
    def has_variable(self):
        return any(placement.column.kind.is_variable for placement in self.columns)


def _integer(header, key, minimum=None):
    value = require_keyword(header, key)
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError("invalid integer keyword: " + key)
    return value


def _equal(header, key, expected):
    value = require_keyword(header, key)
    if type(value) is not type(expected) or value != expected:
        raise ValueError("unsupported keyword value: " + key)


def _axes(header, count):
    for key in header.cards:
        if re.fullmatch(r"NAXIS[0-9]+", key):
            number = int(key[5:])
            if number < 1 or number > count or key != "NAXIS" + str(number):
                raise ValueError("unexpected axis keyword")


def _uncompressed(header):
    if header.get("ZIMAGE") is True or header.get("ZTABLE") is True:
        raise ValueError("compressed HDU unsupported")


def build_primary_layout(header):
    _equal(header, "SIMPLE", True)
    _equal(header, "BITPIX", 8)
    _equal(header, "NAXIS", 0)
    _axes(header, 0)
    _uncompressed(header)
    if "XTENSION" in header.cards:
        raise ValueError("primary HDU cannot be an extension")
    for key, value in (("PCOUNT", 0), ("GCOUNT", 1)):
        if key in header.cards:
            _equal(header, key, value)
    if "THEAP" in header.cards:
        raise ValueError("primary HDU cannot declare a heap")
    return PrimaryLayout()


def build_table_layout(header, hdu_index):
    _equal(header, "XTENSION", "BINTABLE")
    _equal(header, "BITPIX", 8)
    _equal(header, "NAXIS", 2)
    _equal(header, "GCOUNT", 1)
    _axes(header, 2)
    _uncompressed(header)
    if "SIMPLE" in header.cards:
        raise ValueError("extension cannot be a primary HDU")
    width = _integer(header, "NAXIS1", 0)
    rows = _integer(header, "NAXIS2", 0)
    fields = _integer(header, "TFIELDS", 0)
    if fields > 999:
        raise ValueError("too many FITS fields")
    for key in header.cards:
        match = re.fullmatch(r"T(?:TYPE|FORM|NULL|SCAL|ZERO)([0-9]+)", key)
        if match and (not 1 <= int(match[1]) <= fields or str(int(match[1])) != match[1]):
            raise ValueError("column keyword outside TFIELDS")
    pcount = _integer(header, "PCOUNT", 0)
    placements = []
    names = set()
    offset = 0
    for index in range(1, fields + 1):
        column = parse_column(header, index)
        if column.name in names:
            raise ValueError("duplicate column name")
        names.add(column.name)
        placements.append(ColumnPlacement(index - 1, offset, column))
        offset += column.kind.byte_width
    if offset != width:
        raise ValueError("column widths do not equal row width")
    row_area = width * rows
    has_variable = any(placement.column.kind.is_variable for placement in placements)
    if "THEAP" in header.cards:
        theap = _integer(header, "THEAP", 0)
    else:
        theap = row_area
    if has_variable:
        # The heap is [THEAP, R+PCOUNT); a gap [R, THEAP) is allowed.
        if not row_area <= theap <= row_area + pcount:
            raise ValueError("THEAP outside the row area and heap")
    else:
        # V1 rule: fixed-only tables keep PCOUNT=0 and no gap.
        if pcount != 0:
            raise ValueError("fixed-only tables require PCOUNT=0")
        if theap != row_area:
            raise ValueError("fixed-only tables accept no heap or gap")
    if max(width, rows, row_area + pcount) > _MAX_SQLITE_INTEGER:
        raise ValueError("unsupported FITS extent")
    return TableLayout(hdu_index, width, rows, tuple(placements), pcount, theap)
