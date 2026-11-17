import struct


J_ELEMENT_BYTES = 4


def validate_fixed_payload(payload, repeat):
    if type(repeat) is not int or repeat <= 0:
        raise ValueError("invalid fixed repeat")
    if not isinstance(payload, bytes) or len(payload) != repeat * J_ELEMENT_BYTES:
        raise ValueError("fixed cell payload length mismatch")


def decode_j_values(payload):
    if not isinstance(payload, bytes) or len(payload) % J_ELEMENT_BYTES:
        raise ValueError("invalid J window")
    return tuple(item[0] for item in struct.iter_unpack(">i", payload))
