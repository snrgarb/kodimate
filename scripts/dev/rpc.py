#!/usr/bin/env python3
"""Send a JSON-RPC request to Kodi over its TCP JSON-RPC socket.

Usage: rpc.py <Method> ['<json params>']

Env:
  KODI_HOST     default 127.0.0.1
  KODI_RPC_PORT default 9090
"""
import json
import os
import socket
import sys


def main():
    if len(sys.argv) < 2:
        print("usage: rpc.py <Method> ['<json params>']", file=sys.stderr)
        return 2

    method = sys.argv[1]
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    host = os.environ.get("KODI_HOST", "127.0.0.1")
    port = int(os.environ.get("KODI_RPC_PORT", "9090"))

    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}

    with socket.create_connection((host, port), timeout=10) as sock:
        sock.sendall(json.dumps(request).encode("utf-8"))
        sock.settimeout(10)

        buf = b""
        decoder = json.JSONDecoder()
        response = None
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            try:
                text = buf.decode("utf-8").lstrip()
            except UnicodeDecodeError:
                continue
            if not text:
                continue
            try:
                response, _ = decoder.raw_decode(text)
                break
            except json.JSONDecodeError:
                continue

    if response is None:
        print("no response from Kodi JSON-RPC", file=sys.stderr)
        return 1

    print(json.dumps(response))
    return 1 if "error" in response else 0


if __name__ == "__main__":
    sys.exit(main())
