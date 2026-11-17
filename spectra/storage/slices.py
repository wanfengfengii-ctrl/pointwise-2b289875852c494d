from dataclasses import dataclass


@dataclass(frozen=True)
class SliceWindow:
    start: int
    stop: int

    @property
    def byte_start(self):
        return 4 * self.start

    @property
    def byte_count(self):
        return 4 * (self.stop - self.start)

    @property
    def byte_stop(self):
        return 4 * self.stop


def normalize_slice(length, start, stop):
    if type(length) is not int or length < 0:
        raise ValueError("invalid cell length")
    if any(type(value) is not int or value < 0 for value in (start, stop)):
        raise ValueError("slice bounds must be nonnegative integers")
    if start > stop:
        raise ValueError("slice start exceeds stop")
    return SliceWindow(min(start, length), min(stop, length))
