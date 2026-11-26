#!/usr/bin/env python3
"""Forward 127.0.0.1:local_port → host:remote_port (daemon).

Used so OpenHands Settings can use http://127.0.0.1:<port>/mcp for both:
- Canvas Test (host network + published ports), and
- conversation (compose DNS via this forwarder).
"""
from __future__ import annotations

import errno
import selectors
import socket
import sys
import threading


def _pipe(a: socket.socket, b: socket.socket) -> None:
    sel = selectors.DefaultSelector()
    sel.register(a, selectors.EVENT_READ, b)
    sel.register(b, selectors.EVENT_READ, a)
    try:
        while True:
            for key, _ in sel.select(timeout=300):
                src: socket.socket = key.fileobj  # type: ignore[assignment]
                dst: socket.socket = key.data
                try:
                    data = src.recv(65536)
                except OSError:
                    return
                if not data:
                    return
                try:
                    dst.sendall(data)
                except OSError:
                    return
    finally:
        sel.close()
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass


def _handle(client: socket.socket, remote_host: str, remote_port: int) -> None:
    try:
        upstream = socket.create_connection((remote_host, remote_port), timeout=5)
    except OSError:
        client.close()
        return
    t = threading.Thread(target=_pipe, args=(client, upstream), daemon=True)
    t.start()
    _pipe(upstream, client)


def serve(local_port: int, remote_host: str, remote_port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", local_port))
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(f"[mcp-forward] 127.0.0.1:{local_port} busy — skip", flush=True)
            return
        raise
    sock.listen(64)
    print(
        f"[mcp-forward] 127.0.0.1:{local_port} → {remote_host}:{remote_port}",
        flush=True,
    )
    while True:
        client, _ = sock.accept()
        threading.Thread(
            target=_handle, args=(client, remote_host, remote_port), daemon=True
        ).start()


def main() -> int:
    if len(sys.argv) != 4:
        print(
            f"usage: {sys.argv[0]} <local_port> <remote_host> <remote_port}",
            file=sys.stderr,
        )
        return 2
    local_port = int(sys.argv[1])
    remote_host = sys.argv[2]
    remote_port = int(sys.argv[3])
    serve(local_port, remote_host, remote_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
