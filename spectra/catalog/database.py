import sqlite3

from spectra.storage.schema import install_schema, migrate_schema, validate_schema


def configure_connection(connection):
    connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("foreign keys could not be enabled")
    connection.execute("PRAGMA busy_timeout=5000")


def open_database(path):
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        configure_connection(connection)
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            install_schema(connection)
        elif version == 1:
            migrate_schema(connection)
        else:
            validate_schema(connection)
    except BaseException:
        connection.close()
        raise
    return connection
