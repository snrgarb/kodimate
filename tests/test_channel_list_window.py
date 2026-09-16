from kodimate import db
from kodimate.windows.channel_list import ChannelListWindow, GROUPS_LIST_ID, CHANNELS_LIST_ID, \
    TOGGLE_HIDDEN_ID


def _conn(tmp_path):
    return db.open_db(str(tmp_path / "kodimate.db"))


def _seed(conn):
    p1 = conn.execute(
        "INSERT INTO provider (kind, name, enabled, sort_order) VALUES ('m3u', 'P1', 1, 0)"
    ).lastrowid
    p2 = conn.execute(
        "INSERT INTO provider (kind, name, enabled, sort_order) VALUES ('m3u', 'P2', 1, 1)"
    ).lastrowid
    g1 = conn.execute(
        "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, 'Sports', 0)",
        (p1,),
    ).lastrowid
    conn.execute(
        "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, "
        "group_id, position, logo_url) VALUES (?, 'a', 'Alpha', 'alpha', 'http://x/a', ?, 0, "
        "'http://logo/a.png')",
        (p1, g1),
    )
    conn.execute(
        "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, "
        "group_id, position) VALUES (?, 'b', 'Beta', 'beta', 'http://x/b', ?, 1)",
        (p1, g1),
    )
    conn.execute(
        "INSERT INTO channel_override (provider_id, channel_key, hidden) VALUES (?, 'b', 1)",
        (p1,),
    )
    return p1, p2, g1


def _window(conn):
    window = ChannelListWindow('script-kodimate-channel-list.xml', '/addon', 'Main', '1080i',
                                conn=conn)
    window.onInit()
    return window


def test_groups_list_has_all_favourites_and_group(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        groups_control = window.getControl(GROUPS_LIST_ID)
        labels = [item.getLabel() for item in groups_control._items]
        assert labels == ["String 32038", "String 32039", "Sports"]
    finally:
        conn.close()


def test_channels_list_excludes_hidden_by_default(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        channels_control = window.getControl(CHANNELS_LIST_ID)
        labels = [item.getLabel() for item in channels_control._items]
        assert labels == ["Alpha"]
    finally:
        conn.close()


def test_show_hidden_toggle_reveals_hidden_row(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        window.onClick(TOGGLE_HIDDEN_ID)
        channels_control = window.getControl(CHANNELS_LIST_ID)
        labels = [item.getLabel() for item in channels_control._items]
        assert labels == ["Alpha", "Beta"]
        beta = channels_control._items[1]
        assert beta.getProperty('hidden') == '1'
    finally:
        conn.close()


def test_logo_art_set_only_when_logo_url_present(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        window.onClick(TOGGLE_HIDDEN_ID)
        channels_control = window.getControl(CHANNELS_LIST_ID)
        alpha, beta = channels_control._items
        assert alpha.getArt('icon') == 'http://logo/a.png'
        assert beta.getArt('icon') == ''
    finally:
        conn.close()
