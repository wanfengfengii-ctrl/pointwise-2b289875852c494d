def publish_revision(session):
    if session.state != "verified" or not session.connection.in_transaction:
        raise RuntimeError("only verified input can be published")
    summary = session.summary
    cursor = session.connection.execute(
        "UPDATE revisions SET state='published',table_count=?,row_count=?,"
        "cell_count=?,input_bytes=? WHERE revision=? AND state='staging'",
        (summary.table_count, summary.row_count, summary.cell_count,
         summary.input_bytes, session.revision),
    )
    if cursor.rowcount != 1:
        raise ValueError("candidate revision disappeared")
    session.connection.commit()
    session.state = "published"
    return session.revision


def require_published_revision(connection, revision):
    if type(revision) is not int or revision < 1:
        raise KeyError(revision)
    record = connection.execute(
        "SELECT revision FROM revisions WHERE revision=? AND state='published'",
        (revision,),
    ).fetchone()
    if record is None:
        raise KeyError(revision)
    return record[0]
