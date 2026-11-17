class ChunkReader:
    def __init__(self, chunks):
        self._iterator = iter(chunks)
        self._block = b""
        self._offset = 0
        self._ended = False
        self._position = 0

    @property
    def position(self):
        return self._position

    def _available(self):
        while self._offset == len(self._block) and not self._ended:
            try:
                block = next(self._iterator)
            except StopIteration:
                self._ended = True
                self._block = b""
                self._offset = 0
                break
            if not isinstance(block, bytes):
                raise ValueError("input chunks must be bytes")
            self._block = block
            self._offset = 0
        return self._offset < len(self._block)

    def peek_byte(self):
        if not self._available():
            return None
        return self._block[self._offset]

    def read_exact(self, size):
        if type(size) is not int or size < 0:
            raise ValueError("invalid read length")
        if size == 0:
            return b""
        pieces = []
        remaining = size
        while remaining:
            if not self._available():
                raise ValueError("truncated FITS input")
            count = min(remaining, len(self._block) - self._offset)
            pieces.append(self._block[self._offset:self._offset + count])
            self._offset += count
            self._position += count
            remaining -= count
        return b"".join(pieces)

    def iter_exact(self, size):
        """Yield successive pieces covering exactly size bytes.

        Pieces are bounded by the current input block, so arbitrarily large
        regions (gaps, heaps) stream without being materialized whole.
        """
        if type(size) is not int or size < 0:
            raise ValueError("invalid read length")
        remaining = size
        while remaining:
            if not self._available():
                raise ValueError("truncated FITS input")
            count = min(remaining, len(self._block) - self._offset)
            piece = self._block[self._offset:self._offset + count]
            self._offset += count
            self._position += count
            remaining -= count
            yield piece

    def require_eof(self):
        if self.peek_byte() is not None:
            raise ValueError("unexpected trailing input")
