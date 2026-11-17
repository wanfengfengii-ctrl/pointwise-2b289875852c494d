from spectra.fits.stream import ChunkReader
from spectra.fits.hdu import scan_hdus
from spectra.catalog.imports import begin_import, mark_input_verified, abort_import
from spectra.catalog.tables import stage_table
from spectra.catalog.revisions import publish_revision
from spectra.storage.fixed_cells import FixedCellStore
from spectra.storage.variable_cells import VariableStore


def ingest_stream(connection, chunks):
    """Consume a single-pass FITS stream into a candidate revision.

    Fixed cells, variable descriptors and archive-owned heap chunks are all
    staged inside the one import transaction; only a fully validated stream
    (every HDU, padding byte and descriptor range) is published, and any
    failure rolls the candidate back without touching older revisions.
    """
    session = begin_import(connection)
    fixed_store = FixedCellStore(connection)
    variable_store = VariableStore(connection)
    previous = None
    staged_tables = staged_rows = staged_cells = 0

    def finish_table():
        if previous is not None:
            variable_store.finish_table(session.revision, previous)
            fixed_store.verify_table(session.revision, previous)
            variable_store.verify_table(session.revision, previous)

    def on_table(layout):
        nonlocal previous, staged_tables
        finish_table()
        stage_table(session, layout)
        variable_store.begin_table(session.revision, layout)
        previous = layout
        staged_tables += 1

    def on_row(layout, row, payload):
        nonlocal staged_rows, staged_cells
        if layout is not previous or len(payload) != layout.row_width:
            raise ValueError("row does not belong to current layout")
        for placement in layout.columns:
            start = placement.offset
            cell = payload[start:start + placement.width]
            if placement.column.kind.is_variable:
                variable_store.write_descriptor(
                    session.revision, layout, row, placement, cell)
            else:
                fixed_store.write(session.revision, layout, row, placement, cell)
            staged_cells += 1
        staged_rows += 1

    def on_heap(layout, offset, data):
        if layout is not previous:
            raise ValueError("heap chunk does not belong to current layout")
        variable_store.write_heap(session.revision, layout, offset, data)

    try:
        summary = scan_hdus(ChunkReader(chunks), on_table, on_row, on_heap)
        finish_table()
        counts = (staged_tables, staged_rows, staged_cells)
        if counts != (summary.table_count, summary.row_count, summary.cell_count):
            raise ValueError("scan and staging counts disagree")
        stored_cells = (fixed_store.count_for_revision(session.revision)
                        + variable_store.count_for_revision(session.revision))
        if stored_cells != summary.cell_count:
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
