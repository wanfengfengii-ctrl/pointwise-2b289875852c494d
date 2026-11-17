from dataclasses import dataclass


@dataclass
class ImportSession:
    connection: object
    revision: int
    state: str = "staging"
    summary: object = None

    def require_staging(self):
        if self.state != "staging" or not self.connection.in_transaction:
            raise RuntimeError("import session is not staging")


def begin_import(connection):
    if connection.in_transaction:
        raise RuntimeError("another import transaction is active")
    connection.execute("BEGIN IMMEDIATE")
    try:
        cursor = connection.execute("INSERT INTO revisions(state) VALUES ('staging')")
        return ImportSession(connection, cursor.lastrowid)
    except BaseException:
        try:
            connection.rollback()
        except BaseException:
            pass
        raise


def mark_input_verified(session, summary):
    session.require_staging()
    if summary.table_count < 1 or summary.input_bytes % 2880:
        raise ValueError("incomplete input summary")
    session.summary = summary
    session.state = "verified"


def abort_import(session):
    if session.state == "published":
        return
    try:
        if session.connection.in_transaction:
            session.connection.rollback()
    finally:
        session.state = "aborted"
