from dataclasses import dataclass
import re


@dataclass(frozen=True)
class FixedJType:
    repeat: int

    def __post_init__(self):
        if type(self.repeat) is not int or self.repeat <= 0:
            raise ValueError("fixed repeat must be positive")

    @property
    def is_variable(self):
        return False

    @property
    def byte_width(self):
        return 4 * self.repeat

    @property
    def tform(self):
        return str(self.repeat) + "J"


@dataclass(frozen=True)
class VariableJType:
    # A P/Q descriptor cell: the array payload lives in the heap, never inline.
    letter: str

    def __post_init__(self):
        if self.letter not in ("P", "Q"):
            raise ValueError("unsupported variable descriptor")

    @property
    def is_variable(self):
        return True

    @property
    def repeat(self):
        # The descriptor count, not a claimed common array length.
        return 1

    @property
    def count_width(self):
        return 4 if self.letter == "P" else 8

    @property
    def byte_width(self):
        return 2 * self.count_width

    @property
    def tform(self):
        return "1" + self.letter + "J"


_FIXED_TFORM = re.compile(r"([0-9]*)J\Z")
_VARIABLE_TFORM = re.compile(r"1?([PQ])J\Z")


def parse_fixed_tform(value):
    kind = parse_column_tform(value)
    if kind.is_variable:
        raise ValueError("only fixed J columns are supported")
    return kind


def parse_column_tform(value):
    if not isinstance(value, str):
        raise ValueError("TFORM must be a string")
    text = value.strip()
    match = _FIXED_TFORM.fullmatch(text)
    if match is not None:
        return FixedJType(int(match[1]) if match[1] else 1)
    match = _VARIABLE_TFORM.fullmatch(text)
    if match is not None:
        return VariableJType(match[1])
    raise ValueError("unsupported TFORM")
