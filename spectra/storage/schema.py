import sqlite3


SCHEMA_VERSION = 1
SCHEMA_SQL = """
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


_EXPECTED_COLUMNS = {
    "revisions": ("revision", "state", "table_count", "row_count", "cell_count", "input_bytes"),
    "tables": ("revision", "hdu_index", "row_count", "row_width", "column_count"),
    "columns": ("revision", "hdu_index", "ordinal", "name", "repeat", "tnull",
                "scale_num", "scale_den", "zero_num", "zero_den"),
    "fixed_cells": ("revision", "hdu_index", "row_index", "ordinal", "payload"),
}


def install_schema(connection):
    existing = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    if existing:
        raise ValueError("refusing to initialize a nonempty database")
    try:
        connection.executescript(
            "BEGIN;\n" + SCHEMA_SQL + "\nPRAGMA user_version=1;\nCOMMIT;"
        )
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
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
