#!/usr/bin/env python3
"""Execute a Kodi builtin function via the EventServer (UDP 9777).

Usage: builtin.py 'UpdateLocalAddons()'

Env:
  KODI_HOST          default 127.0.0.1
  KODI_EVENT_PORT    default 9777

Implements the minimal subset of the Kodi EventClient binary protocol
needed to send PT_ACTION/ACTION_EXECBUILTIN packets, per
tools/EventClients/lib/python/xbmcclient.py in xbmc/xbmc.
"""
import os
import socket
import struct
import sys

SIG = b"XBMC"
MAJOR = 2
MINOR = 0

PT_HELO = 0x01
PT_BYE = 0x02
PT_ACTION = 0x0A

ACTION_EXECBUILTIN = 0x01

DEVICE_NAME = b"kodimate-dev"


def pack_packet(packet_type, payload):
    header = struct.pack(
        "!4sBBHIIHI10s",
        SIG,
        MAJOR,
        MINOR,
        packet_type,
        1,  # seq
        1,  # maxseq
        len(payload),
        0,  # uid
        b"\x00" * 10,
    )
    return header + payload


def main():
    if len(sys.argv) != 2:
        print("usage: builtin.py '<Builtin()>'", file=sys.stderr)
        return 2

    builtin = sys.argv[1]

    host = os.environ.get("KODI_HOST", "127.0.0.1")
    port = int(os.environ.get("KODI_EVENT_PORT", "9777"))

    helo_payload = DEVICE_NAME + b"\x00" + struct.pack("!BHII", 0, 0, 0, 0)
    action_payload = struct.pack("!B", ACTION_EXECBUILTIN) + builtin.encode("utf-8") + b"\x00"

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(pack_packet(PT_HELO, helo_payload), (host, port))
        sock.sendto(pack_packet(PT_ACTION, action_payload), (host, port))
        sock.sendto(pack_packet(PT_BYE, b""), (host, port))
    finally:
        sock.close()

    print(f"sent EXECBUILTIN: {builtin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
