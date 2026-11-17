from spectra.catalog.database import open_database
from spectra.catalog.ingestion import ingest_fixed_stream
from spectra.access.metadata import describe_revision
from spectra.access.cells import read_cell
from spectra.access.selection import select_rows


class Archive:
    def __init__(self, database_path):
        self._connection = open_database(database_path)

    def _require_open(self):
        if self._connection is None:
            raise RuntimeError("archive is closed")
        return self._connection

    def ingest(self, chunks):
        return ingest_fixed_stream(self._require_open(), chunks)

    def describe(self, revision):
        return describe_revision(self._require_open(), revision)

    def cell(self, revision, row, column, start, stop):
        return read_cell(self._require_open(), revision, row, column, start, stop)

    def select_rows(self, revision, column, lower, upper):
        return select_rows(self._require_open(), revision, column, lower, upper)

    def close(self):
        if self._connection is not None:
            connection = self._connection
            self._connection = None
            connection.close()
