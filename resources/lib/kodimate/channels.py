# -*- coding: utf-8 -*-
"""Pure-SQL queries for the Channel List window (issue #19)."""

_BASE_JOIN = """
    FROM channel c
    JOIN provider p ON p.id = c.provider_id
    LEFT JOIN channel_override o
        ON o.provider_id = c.provider_id AND o.channel_key = c.channel_key
    WHERE c.stale_since IS NULL
    AND p.enabled = 1 AND p.deleted_at IS NULL
"""


def list_groups(conn):
    rows = conn.execute(
        """
        SELECT g.id, g.provider_id, g.name
        FROM channel_group g
        JOIN provider p ON p.id = g.provider_id
        WHERE p.enabled = 1 AND p.deleted_at IS NULL
        AND EXISTS (
            SELECT 1 FROM channel c
            WHERE c.group_id = g.id AND c.stale_since IS NULL
        )
        ORDER BY p.sort_order, p.id, g.sort_order, g.id
        """
    ).fetchall()
    return [{'id': row[0], 'provider_id': row[1], 'name': row[2]} for row in rows]


def list_channels(conn, group_id=None, favourites=False, show_hidden=False):
    """Listable channels, each including 'epg_channel_id' (used by the
    Guide window to look up programmes via list_programmes())."""
    where = []
    params = []
    if not show_hidden:
        where.append("COALESCE(o.hidden, 0) = 0")
    if group_id is not None:
        where.append("c.group_id = ?")
        params.append(group_id)
    if favourites:
        where.append("o.favourite = 1")

    order_by = "p.sort_order, p.id, c.position, c.id"
    if favourites:
        order_by = "o.favourite_order IS NULL, o.favourite_order, p.sort_order, p.id, c.position, c.id"

    sql = (
        "SELECT c.id, c.provider_id, c.channel_key, c.name, c.logo_url, "
        "COALESCE(o.number, c.provider_number + p.number_offset, c.position + p.number_offset) "
        "AS number, COALESCE(o.hidden, 0) AS hidden, c.epg_channel_id, "
        "COALESCE(c.catchup_days, p.catchup_days_default) AS catchup_days"
        + _BASE_JOIN
        + ("" if not where else " AND " + " AND ".join(where))
        + " ORDER BY " + order_by
    )
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            'id': row[0],
            'provider_id': row[1],
            'channel_key': row[2],
            'name': row[3],
            'logo_url': row[4],
            'number': row[5],
            'hidden': bool(row[6]),
            'epg_channel_id': row[7],
            'catchup_days': row[8],
        }
        for row in rows
    ]


def list_programmes(conn, channel_ids, window_start, window_end):
    """Programme rows overlapping [window_start, window_end) (ISO UTC
    strings) per channel id, for channels with a matched EPG channel.
    Returns {channel_id: [{'start', 'end', 'title', 'description'}, ...]},
    sorted by start; channel ids with no matching EPG channel or no
    overlapping rows map to an empty list."""
    result = {cid: [] for cid in channel_ids}
    if not channel_ids:
        return result

    placeholders = ','.join('?' for _ in channel_ids)
    rows = conn.execute(
        "SELECT c.id, pr.start, pr.end, pr.title, pr.description, pr.catchup_id "
        "FROM channel c "
        "JOIN epg_source e ON e.provider_id = c.provider_id "
        "JOIN programme pr ON pr.epg_source_id = e.id "
        "AND pr.xmltv_channel_id = c.epg_channel_id "
        "WHERE c.id IN (" + placeholders + ") AND c.epg_channel_id IS NOT NULL "
        "AND pr.start < ? AND pr.end > ? "
        "ORDER BY c.id, pr.start",
        list(channel_ids) + [window_end, window_start],
    ).fetchall()
    for row in rows:
        result[row[0]].append({
            'start': row[1], 'end': row[2], 'title': row[3], 'description': row[4] or '',
            'catchup_id': row[5],
        })
    return result


def now_titles(conn, channel_ids, now_iso):
    """{channel_id: title} for channels with a programme airing at now_iso.
    Where several rows cover now_iso (overlapping EPG data), the
    later-starting one takes precedence, matching Kodi's own EPG
    behaviour; rows are sorted by start, so that is the last row."""
    programmes = list_programmes(conn, channel_ids, now_iso, now_iso)
    return {
        cid: rows[-1]['title'] for cid, rows in programmes.items() if rows
    }
