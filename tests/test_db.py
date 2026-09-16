from kodimate import db

EXPECTED_TABLES = {
    'provider', 'epg_source', 'programme_staging', 'channel_group',
    'channel', 'channel_override', 'programme', 'meta',
}


def _tables(conn):
    return {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}


def test_open_db_creates_v1_schema(tmp_path):
    conn = db.open_db(str(tmp_path / "kodimate.db"))
    try:
        assert EXPECTED_TABLES <= _tables(conn)
        version = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert version == str(db.SCHEMA_VERSION)
    finally:
        conn.close()


def test_open_db_sets_pragmas(tmp_path):
    conn = db.open_db(str(tmp_path / "kodimate.db"))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == 'wal'
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        conn.close()


def test_open_db_second_open_is_a_no_op(tmp_path):
    path = str(tmp_path / "kodimate.db")

    conn1 = db.open_db(path)
    tables1 = _tables(conn1)
    version1 = conn1.execute(
        "SELECT value FROM meta WHERE key='schema_version'"
    ).fetchone()[0]
    conn1.close()

    conn2 = db.open_db(path)
    tables2 = _tables(conn2)
    version2 = conn2.execute(
        "SELECT value FROM meta WHERE key='schema_version'"
    ).fetchone()[0]
    conn2.close()

    assert tables1 == tables2
    assert version1 == version2
