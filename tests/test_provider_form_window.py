from kodimate import db
from kodimate.windows.provider_form import ProviderFormWindow


def _conn(tmp_path):
    return db.open_db(str(tmp_path / "kodimate.db"))


def _window(conn, kind):
    window = ProviderFormWindow('script-kodimate-provider-form.xml', '/addon', 'Main', '1080i',
                                 conn=conn, kind=kind, provider_id=None)
    window.onInit()
    return window


def test_title_label_for_xtream_kind(tmp_path):
    conn = _conn(tmp_path)
    try:
        window = _window(conn, 'xtream')
        assert window.getControl(100).getLabel() == "String 32052"
    finally:
        conn.close()


def test_title_label_for_m3u_kind(tmp_path):
    conn = _conn(tmp_path)
    try:
        window = _window(conn, 'm3u')
        assert window.getControl(100).getLabel() == "String 32017"
    finally:
        conn.close()
