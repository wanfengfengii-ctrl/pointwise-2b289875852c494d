from dataclasses import dataclass
from types import MappingProxyType
import re

from spectra.fits.cards import parse_card
from spectra.fits.padding import read_header_padding


_CRITICAL = re.compile(
    r"(?:SIMPLE|XTENSION|BITPIX|NAXIS\d*|PCOUNT|GCOUNT|TFIELDS|THEAP|"
    r"EXTEND|ZIMAGE|ZTABLE|T(?:TYPE|FORM|NULL|SCAL|ZERO)\d+)\Z"
)


@dataclass(frozen=True)
class Header:
    cards: object

    def get(self, keyword, default=None):
        card = self.cards.get(keyword)
        return default if card is None else card.value

    def lexical(self, keyword, default):
        card = self.cards.get(keyword)
        if card is None:
            return default
        if card.value_text is None:
            raise ValueError("keyword has no assigned value")
        return card.value_text.split("/", 1)[0].strip()


def require_keyword(header, keyword):
    card = header.cards.get(keyword)
    if card is None or card.value_text is None:
        raise ValueError("missing required keyword: " + keyword)
    return card.value


def read_header(reader):
    cards = {}
    size = 0
    while True:
        card = parse_card(reader.read_exact(80))
        size += 80
        if card.keyword == "END":
            break
        if card.keyword in ("", "COMMENT", "HISTORY"):
            continue
        if _CRITICAL.fullmatch(card.keyword):
            if card.keyword in cards:
                raise ValueError("duplicate keyword: " + card.keyword)
            if card.value_text is None:
                raise ValueError("unassigned structural keyword")
        cards.setdefault(card.keyword, card)
    read_header_padding(reader, size)
    return Header(MappingProxyType(cards))
