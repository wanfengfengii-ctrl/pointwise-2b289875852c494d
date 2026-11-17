from spectra.catalog.revisions import require_published_revision
from spectra.catalog.tables import load_catalog


def describe_revision(connection, revision):
    require_published_revision(connection, revision)
    tables = []
    for hdu, rows, columns in load_catalog(connection, revision):
        public_columns = []
        for ordinal, column in columns:
            public_columns.append({
                "name": column.name,
                "tform": column.kind.tform,
                "repeat": column.repeat,
                "tnull": column.tnull,
                "tscal": column.scaling.scale,
                "tzero": column.scaling.zero,
            })
        tables.append({
            "hdu_index": hdu,
            "row_count": rows,
            "columns": public_columns,
        })
    return {"revision": revision, "tables": tables}
