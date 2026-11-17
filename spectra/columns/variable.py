"""P/Q descriptor decoding and range validation.

A descriptor is never the array's inline payload: it only states an element
count and a byte offset relative to its own HDU's THEAP. Validation here is
the fits-side guarantee handed to the archive side together with the column's
J interpretation; every referenced range is checked before publication, even
if it is never read.
"""
from spectra.columns.types import VariableJType

J_ELEMENT_BYTES = 4


def decode_descriptor(kind, payload):
    if not isinstance(kind, VariableJType):
        raise ValueError("not a variable column")
    half = kind.count_width
    if not isinstance(payload, bytes) or len(payload) != 2 * half:
        raise ValueError("descriptor length mismatch")
    count = int.from_bytes(payload[:half], "big", signed=True)
    offset = int.from_bytes(payload[half:], "big", signed=True)
    return count, offset


def validate_descriptor_range(count, offset, heap_length):
    if type(count) is not int or type(offset) is not int:
        raise ValueError("descriptor values must be integers")
    if type(heap_length) is not int or heap_length < 0:
        raise ValueError("invalid heap length")
    if count < 0:
        raise ValueError("negative variable element count")
    if count == 0:
        # An empty array ignores its offset, even a negative one.
        return
    if offset < 0:
        raise ValueError("negative variable heap offset")
    if offset + J_ELEMENT_BYTES * count > heap_length:
        raise ValueError("variable range extends beyond the heap")
