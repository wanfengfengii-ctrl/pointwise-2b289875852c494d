FITS_BLOCK_SIZE = 2880


def padding_length(size):
    if type(size) is not int or size < 0:
        raise ValueError("invalid FITS extent")
    return (-size) % FITS_BLOCK_SIZE


def _read_padding(reader, size, expected):
    remaining = padding_length(size)
    while remaining:
        count = min(remaining, FITS_BLOCK_SIZE)
        data = reader.read_exact(count)
        if data != bytes([expected]) * count:
            raise ValueError("invalid FITS padding")
        remaining -= count


def read_header_padding(reader, header_size):
    _read_padding(reader, header_size, 32)


def read_data_padding(reader, data_size):
    _read_padding(reader, data_size, 0)
