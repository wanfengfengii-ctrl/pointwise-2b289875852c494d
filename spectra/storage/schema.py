import sqlite3


SCHEMA_VERSION = 2

# V1 core tables. The columns table gains a trailing kind column so that a
# V1 archive migrated by ALTER TABLE and a fresh V2 archive agree on
# PRAGMA table_info order.
_CORE_SCHEMA_SQL = """
CREATE TABLE revisions(
    revision INTEGER PRIMARY KEY,
    state TEXT NOT NULL CHECK(state IN ('staging','published')),
    table_count INTEGER NOT NULL DEFAULT 0,
    row_count INTEGER NOT NULL DEFAULT 0,
    cell_count INTEGER NOT NULL DEFAULT 0,
    input_bytes INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE tables(
    revision INTEGER NOT NULL REFERENCES revisions(revision) ON DELETE CASCADE,
    hdu_index INTEGER NOT NULL CHECK(hdu_index > 0),
    row_count INTEGER NOT NULL CHECK(row_count >= 0),
    row_width INTEGER NOT NULL CHECK(row_width >= 0),
    column_count INTEGER NOT NULL CHECK(column_count >= 0),
    PRIMARY KEY(revision,hdu_index)
);
CREATE TABLE columns(
    revision INTEGER NOT NULL,
    hdu_index INTEGER NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    name TEXT NOT NULL,
    repeat INTEGER NOT NULL CHECK(repeat > 0),
    tnull INTEGER,
    scale_num TEXT NOT NULL,
    scale_den TEXT NOT NULL,
    zero_num TEXT NOT NULL,
    zero_den TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'fixed' CHECK(kind IN ('fixed','P','Q')),
    PRIMARY KEY(revision,hdu_index,ordinal),
    UNIQUE(revision,hdu_index,name),
    FOREIGN KEY(revision,hdu_index) REFERENCES tables(revision,hdu_index) ON DELETE CASCADE
);
CREATE TABLE fixed_cells(
    revision INTEGER NOT NULL,
    hdu_index INTEGER NOT NULL,
    row_index INTEGER NOT NULL CHECK(row_index >= 0),
    ordinal INTEGER NOT NULL,
    payload BLOB NOT NULL,
    PRIMARY KEY(revision,hdu_index,row_index,ordinal),
    FOREIGN KEY(revision,hdu_index,ordinal)
        REFERENCES columns(revision,hdu_index,ordinal) ON DELETE CASCADE
);
"""

# V2 variable-array ownership: one descriptor row per variable cell, one
# heaps row per variable table recording the durable heap extent, and the
# archive-owned heap bytes themselves in fixed-size chunks.
VARIABLE_SCHEMA_SQL = """
CREATE TABLE variable_descriptors(
    revision INTEGER NOT NULL,
    hdu_index INTEGER NOT NULL,
    row_index INTEGER NOT NULL CHECK(row_index >= 0),
    ordinal INTEGER NOT NULL,
    element_count INTEGER NOT NULL CHECK(element_count >= 0),
    heap_offset INTEGER NOT NULL,
    PRIMARY KEY(revision,hdu_index,row_index,ordinal),
    FOREIGN KEY(revision,hdu_index,ordinal)
        REFERENCES columns(revision,hdu_index,ordinal) ON DELETE CASCADE
);
CREATE TABLE heaps(
    revision INTEGER NOT NULL,
    hdu_index INTEGER NOT NULL,
    heap_length INTEGER NOT NULL CHECK(heap_length >= 0),
    PRIMARY KEY(revision,hdu_index),
    FOREIGN KEY(revision,hdu_index) REFERENCES tables(revision,hdu_index) ON DELETE CASCADE
);
CREATE TABLE heap_chunks(
    revision INTEGER NOT NULL,
    hdu_index INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL CHECK(chunk_index >= 0),
    payload BLOB NOT NULL,
    PRIMARY KEY(revision,hdu_index,chunk_index),
    FOREIGN KEY(revision,hdu_index) REFERENCES tables(revision,hdu_index) ON DELETE CASCADE
);
"""

SCHEMA_SQL = _CORE_SCHEMA_SQL + VARIABLE_SCHEMA_SQL

MIGRATION_SQL = """
ALTER TABLE columns ADD COLUMN kind TEXT NOT NULL DEFAULT 'fixed'
    CHECK(kind IN ('fixed','P','Q'));
""" + VARIABLE_SCHEMA_SQL


_EXPECTED_COLUMNS = {
    "revisions": ("revision", "state", "table_count", "row_count", "cell_count", "input_bytes"),
    "tables": ("revision", "hdu_index", "row_count", "row_width", "column_count"),
    "columns": ("revision", "hdu_index", "ordinal", "name", "repeat", "tnull",
                "scale_num", "scale_den", "zero_num", "zero_den", "kind"),
    "fixed_cells": ("revision", "hdu_index", "row_index", "ordinal", "payload"),
    "variable_descriptors": ("revision", "hdu_index", "row_index", "ordinal",
                             "element_count", "heap_offset"),
    "heaps": ("revision", "hdu_index", "heap_length"),
    "heap_chunks": ("revision", "hdu_index", "chunk_index", "payload"),
}


def _run_script(connection, script, version):
    try:
        connection.executescript(
            "BEGIN;\n" + script + "\nPRAGMA user_version=" + str(version) + ";\nCOMMIT;"
        )
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def install_schema(connection):
    existing = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    if existing:
        raise ValueError("refusing to initialize a nonempty database")
    _run_script(connection, SCHEMA_SQL, SCHEMA_VERSION)
    validate_schema(connection)


def migrate_schema(connection):
    # A V1 archive keeps every published byte; the new tables start empty and
    # existing columns are fixed J by definition.
    _run_script(connection, MIGRATION_SQL, SCHEMA_VERSION)
    validate_schema(connection)


def validate_schema(connection):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        raise ValueError("unsupported archive schema")
    for name, expected in _EXPECTED_COLUMNS.items():
        actual = tuple(row[1] for row in connection.execute("PRAGMA table_info(" + name + ")"))
        if actual != expected:
            raise ValueError("invalid archive table: " + name)
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise sqlite3.DatabaseError("archive foreign key violation")
