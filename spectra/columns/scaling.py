from dataclasses import dataclass
from fractions import Fraction
import re


_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EDed][+-]?\d+)?\Z")


@dataclass(frozen=True)
class Scaling:
    scale: Fraction
    zero: Fraction

    def __post_init__(self):
        if not isinstance(self.scale, Fraction) or not isinstance(self.zero, Fraction):
            raise ValueError("scaling requires exact fractions")


def _fraction(text):
    if not isinstance(text, str) or not _NUMBER.fullmatch(text):
        raise ValueError("invalid finite FITS number")
    return Fraction(text.replace("D", "E").replace("d", "e"))


def parse_scaling(scale="1", zero="0"):
    return Scaling(_fraction(scale), _fraction(zero))


def apply_scaling(raw, scaling):
    return raw * scaling.scale + scaling.zero
