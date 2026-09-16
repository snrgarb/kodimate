# -*- coding: utf-8 -*-
"""Background Refresh service loop logic (docs/design/refresh-ipc.md, ADR 0003).

All Kodi interaction is injected so this is testable without xbmc*:

- ``props``: object with ``get(key) -> str`` and ``set(key, value)`` for the
  ``script.kodimate.``-prefixed Window(10000) properties, addressed here by
  their unprefixed name (``refresh_request``, ``refreshing``,
  ``db_generation``, ``refresh_result.<id>``); the real adapter built in
  service.py adds the prefix.
- ``notify``: callable ``(generation, provider_ids)`` -> NotifyAll wake-up.
- ``fetcher``: callable ``(source, user_agent) -> text``, defaults to
  ``fetch.fetch_playlist``.
- ``now``: callable returning the current UTC ``datetime``, defaults to
  ``datetime.utcnow``.
- ``settings``: dict-like with ``refresh_interval_hours`` (default 12) and
  ``refresh_on_startup`` (default True).
"""
from datetime import datetime, timedelta

from . import fetch, ingest, m3u, xtream

_ISO_FORMAT = '%Y-%m-%dT%H:%M:%SZ'


def _iso(dt):
    return dt.strftime(_ISO_FORMAT)


class RefreshService(object):
    def __init__(self, conn, props, notify, fetcher=None, now=None, settings=None):
        self.conn = conn
        self.props = props
        self.notify = notify
        self.fetcher = fetcher or fetch.fetch_playlist
        self.now = now or datetime.utcnow
        self.settings = settings or {}
        self.generation = 0

        self._queue = []
        self._queued_ids = set()
        self._in_flight = None
        self._startup_done = False
        self._last_sweep = None

    # -- startup ---------------------------------------------------------

    def on_start(self):
        self.conn.execute("DELETE FROM programme_staging")

        deleted_ids = [
            row[0] for row in self.conn.execute(
                "SELECT id FROM provider WHERE deleted_at IS NOT NULL"
            ).fetchall()
        ]
        for provider_id in deleted_ids:
            self.conn.execute(
                "DELETE FROM programme WHERE epg_source_id IN "
                "(SELECT id FROM epg_source WHERE provider_id = ?)",
                (provider_id,),
            )
            for table in ('epg_source', 'channel_group', 'channel', 'channel_override'):
                self.conn.execute(
                    "DELETE FROM {0} WHERE provider_id = ?".format(table), (provider_id,)
                )
            self.conn.execute("DELETE FROM provider WHERE id = ?", (provider_id,))
        if deleted_ids:
            self.generation += 1

        self.props.set('refreshing', '')
        self.props.set('db_generation', str(self.generation))

    # -- per-second tick ---------------------------------------------------

    def _enabled_provider_ids(self):
        return [
            row[0] for row in self.conn.execute(
                "SELECT id FROM provider WHERE enabled = 1 AND deleted_at IS NULL"
            ).fetchall()
        ]

    def _enqueue(self, provider_id, requested_by_ui=False):
        if provider_id == self._in_flight or provider_id in self._queued_ids:
            return
        self._queue.append((provider_id, requested_by_ui))
        self._queued_ids.add(provider_id)

    def _requeue(self, provider_id, requested_by_ui):
        # Used when re-queuing the provider currently in flight (a
        # config_version change mid-refresh): _enqueue's in-flight guard
        # would otherwise refuse it since it hasn't been cleared yet.
        if provider_id in self._queued_ids:
            return
        self._queue.append((provider_id, requested_by_ui))
        self._queued_ids.add(provider_id)

    def _consume_request(self):
        request = self.props.get('refresh_request') or ''
        if not request:
            return
        self.props.set('refresh_request', '')

        ids_part, _, ui_flag = request.partition(';')
        requested_by_ui = ui_flag == 'ui'
        ids_part = ids_part.strip()
        if ids_part == 'all':
            ids = self._enabled_provider_ids()
        else:
            ids = []
            for token in ids_part.split(','):
                token = token.strip()
                if not token:
                    continue
                try:
                    ids.append(int(token))
                except ValueError:
                    continue
        for provider_id in ids:
            self._enqueue(provider_id, requested_by_ui)

    def _due_for_sweep(self):
        if not self._startup_done:
            self._startup_done = True
            self._last_sweep = self.now()
            return bool(self.settings.get('refresh_on_startup', True))

        interval_hours = self.settings.get('refresh_interval_hours', 12)
        if self._last_sweep is not None and \
                self.now() - self._last_sweep >= timedelta(hours=interval_hours):
            self._last_sweep = self.now()
            return True
        return False

    def tick(self):
        self._consume_request()

        if self._due_for_sweep():
            for provider_id in self._enabled_provider_ids():
                self._enqueue(provider_id, requested_by_ui=False)

        if self._queue and self._in_flight is None:
            provider_id, requested_by_ui = self._queue.pop(0)
            self._queued_ids.discard(provider_id)
            self._in_flight = provider_id
            self.props.set('refreshing', str(provider_id))
            try:
                self._refresh_one(provider_id, requested_by_ui)
            finally:
                self._in_flight = None
                self.props.set(
                    'refreshing', ','.join(str(p) for p, _ in self._queue)
                )

    # -- one provider ------------------------------------------------------

    def _fetch_provider_row(self, provider_id):
        cur = self.conn.execute("SELECT * FROM provider WHERE id = ?", (provider_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    def _fail(self, provider_id, requested_by_ui, message):
        message = str(message)[:200]
        self.conn.execute(
            "UPDATE provider SET last_error = ? WHERE id = ?", (message, provider_id)
        )
        if requested_by_ui:
            self.props.set('refresh_result.{0}'.format(provider_id), 'error:{0}'.format(message))

    def _refresh_one(self, provider_id, requested_by_ui):
        row = self._fetch_provider_row(provider_id)
        if row is None or not row['enabled'] or row['deleted_at']:
            return

        config_version = row['config_version']

        try:
            if row['kind'] == 'm3u':
                text = self.fetcher(row['m3u_url'], row['user_agent'])
                outcome = ingest.refresh_m3u_provider(
                    self.conn, provider_id, text, self.now(),
                    expected_config_version=config_version,
                )
            else:
                host, username, password = row['xtream_host'], row['xtream_username'], row['xtream_password']
                account = xtream.fetch_account(host, username, password, row['user_agent'], self.fetcher)
                categories = xtream.fetch_categories(host, username, password, row['user_agent'], self.fetcher)
                streams = xtream.fetch_streams(host, username, password, row['user_agent'], self.fetcher)
                outcome = ingest.refresh_xtream_provider(
                    self.conn, provider_id, account, categories, streams, self.now(),
                    expected_config_version=config_version,
                )
        except ingest.ConfigVersionChanged:
            still_here = self.conn.execute(
                "SELECT 1 FROM provider WHERE id = ? AND deleted_at IS NULL", (provider_id,)
            ).fetchone()
            if still_here:
                self._requeue(provider_id, requested_by_ui)
            return
        except (fetch.FetchError, m3u.M3UError) as exc:
            self._fail(provider_id, requested_by_ui, exc)
            return
        except Exception as exc:  # noqa: BLE001 - one bad provider must not kill the loop
            self._fail(provider_id, requested_by_ui, exc)
            return

        self.conn.execute(
            "UPDATE provider SET last_refresh_at = ?, last_error = NULL WHERE id = ?",
            (_iso(self.now()), provider_id),
        )
        self.generation += 1
        self.props.set('db_generation', str(self.generation))
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.notify(self.generation, [provider_id])
        if requested_by_ui:
            self.props.set('refresh_result.{0}'.format(provider_id), 'ok')
        return outcome
