from dataclasses import dataclass
from fractions import Fraction
import re


_KEYWORD = re.compile(r"[A-Z0-9_-]{0,8}\Z")
_INTEGER = re.compile(r"[+-]?\d+\Z")
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EDed][+-]?\d+)?\Z")


@dataclass(frozen=True)
class Card:
    keyword: str
    value: object
    value_text: str | None


def parse_card_value(text):
    text = text.lstrip()
    if text.startswith("'"):
        result = []
        index = 1
        while index < len(text):
            char = text[index]
            if char == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    result.append("'")
                    index += 2
                    continue
                tail = text[index + 1:].strip()
                if tail and not tail.startswith("/"):
                    raise ValueError("characters after string value")
                return "".join(result).rstrip()
            result.append(char)
            index += 1
        raise ValueError("unterminated FITS string")
    token = text.split("/", 1)[0].strip()
    if token in ("T", "F"):
        return token == "T"
    if _INTEGER.fullmatch(token):
        return int(token)
    if _NUMBER.fullmatch(token):
        return Fraction(token.replace("D", "E").replace("d", "e"))
    raise ValueError("unsupported FITS value")


def parse_card(raw):
    if not isinstance(raw, bytes) or len(raw) != 80:
        raise ValueError("a card must contain 80 bytes")
    if any(byte < 32 or byte > 126 for byte in raw):
        raise ValueError("non-printable FITS header")
    text = raw.decode("ascii")
    keyword = text[:8].rstrip()
    if not _KEYWORD.fullmatch(keyword):
        raise ValueError("invalid FITS keyword")
    if keyword == "END":
        if text[8:].strip():
            raise ValueError("END has a value")
        return Card(keyword, None, None)
    if keyword in ("", "COMMENT", "HISTORY"):
        return Card(keyword, text[8:], None)
    if text[8:10] != "= ":
        return Card(keyword, text[8:], None)
    value_text = text[10:]
    return Card(keyword, parse_card_value(value_text), value_text)
