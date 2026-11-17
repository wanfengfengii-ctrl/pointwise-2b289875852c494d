def parse_tnull(value):
    if value is None:
        return None
    if type(value) is not int or not -(1 << 31) <= value < (1 << 31):
        raise ValueError("TNULL must be a signed 32-bit integer")
    return value


def is_raw_null(raw, tnull):
    return tnull is not None and raw == tnull
