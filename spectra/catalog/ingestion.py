from spectra.fits.stream import ChunkReader
from spectra.fits.hdu import scan_fixed_hdus
from spectra.catalog.imports import begin_import, mark_input_verified, abort_import
from spectra.catalog.tables import stage_table
from spectra.catalog.revisions import publish_revision
from spectra.storage.fixed_cells import FixedCellStore


def ingest_fixed_stream(connection, chunks):
    session = begin_import(connection)
    store = FixedCellStore(connection)
    previous = None
    staged_tables = staged_rows = staged_cells = 0

    def finish_table():
        if previous is not None:
            store.verify_table(session.revision, previous)

    def on_table(layout):
        nonlocal previous, staged_tables
        finish_table()
        stage_table(session, layout)
        previous = layout
        staged_tables += 1

    def on_row(layout, row, payload):
        nonlocal staged_rows, staged_cells
        if layout is not previous or len(payload) != layout.row_width:
            raise ValueError("row does not belong to current layout")
        for placement in layout.columns:
            start = placement.offset
            store.write(
                session.revision, layout, row, placement,
                payload[start:start + placement.width],
            )
            staged_cells += 1
        staged_rows += 1

    try:
        summary = scan_fixed_hdus(ChunkReader(chunks), on_table, on_row)
        finish_table()
        counts = (staged_tables, staged_rows, staged_cells)
        if counts != (summary.table_count, summary.row_count, summary.cell_count):
            raise ValueError("scan and staging counts disagree")
        if store.count_for_revision(session.revision) != summary.cell_count:
            raise ValueError("stored cell count disagrees")
        catalog_counts = connection.execute(
            "SELECT count(*),coalesce(sum(row_count),0),"
            "coalesce(sum(column_count),0) FROM tables WHERE revision=?",
            (session.revision,),
        ).fetchone()
        column_count = connection.execute(
            "SELECT count(*) FROM columns WHERE revision=?", (session.revision,)
        ).fetchone()[0]
        if catalog_counts[:2] != (summary.table_count, summary.row_count):
            raise ValueError("stored table count disagrees")
        if catalog_counts[2] != column_count:
            raise ValueError("stored column count disagrees")
        mark_input_verified(session, summary)
        return publish_revision(session)
    except BaseException:
        try:
            abort_import(session)
        except BaseException:
            pass
        raise
