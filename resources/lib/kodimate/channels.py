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
        "AS number, COALESCE(o.hidden, 0) AS hidden"
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
        }
        for row in rows
    ]
