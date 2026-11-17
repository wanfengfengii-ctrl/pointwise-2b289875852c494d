from dataclasses import dataclass
import re


@dataclass(frozen=True)
class FixedJType:
    repeat: int

    def __post_init__(self):
        if type(self.repeat) is not int or self.repeat <= 0:
            raise ValueError("fixed repeat must be positive")

    @property
    def byte_width(self):
        return 4 * self.repeat

    @property
    def tform(self):
        return str(self.repeat) + "J"


def parse_fixed_tform(value):
    if not isinstance(value, str):
        raise ValueError("TFORM must be a string")
    match = re.fullmatch(r"([0-9]*)J", value.strip())
    if match is None:
        raise ValueError("only fixed J columns are supported")
    return FixedJType(int(match[1]) if match[1] else 1)
