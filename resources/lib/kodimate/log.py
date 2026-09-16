# -*- coding: utf-8 -*-
"""Logging helper: Kodi log wrapper that redacts Xtream credentials (ADR 0002)."""
import re

import xbmc
import xbmcaddon

_PREFIX = "[script.kodimate]"

# http://host/live/USER/PASS/123.ts, and the /movie/, /series/, /timeshift/
# variants of the same Xtream path shape.
_PATH_CREDS_RE = re.compile(r"(/(?:live|movie|series|timeshift)/)[^/]+/[^/]+/")

# http://host/USER/PASS/xmltv.php
_XMLTV_CREDS_RE = re.compile(r"(/)[^/]+/[^/]+(/xmltv\.php)")

# ?username=..., &password=..., &token=...
_QUERY_CREDS_RE = re.compile(r"(?i)\b(username|password|token)=[^&;#\s]*")


def redact(text):
    """Replace Xtream username/password path segments and query credentials with ***."""
    if not text:
        return text
    text = _PATH_CREDS_RE.sub(r"\1***/***/", text)
    text = _XMLTV_CREDS_RE.sub(r"\1***/***\2", text)
    text = _QUERY_CREDS_RE.sub(lambda m: "{0}=***".format(m.group(1)), text)
    return text


def log(msg, level=xbmc.LOGINFO):
    xbmc.log("{0} {1}".format(_PREFIX, redact(msg)), level)


def debug(msg):
    """Emit msg only when the addon's Debug logging setting is on."""
    if xbmcaddon.Addon().getSettingBool('debug'):
        log(msg, xbmc.LOGINFO)
