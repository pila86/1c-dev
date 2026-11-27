#!/usr/bin/env python3
"""Forward 127.0.0.1:local_port → host:remote_port (daemon).

Used so OpenHands Settings can use http://127.0.0.1:<port>/mcp for both:
- Canvas Test (host network + published ports), and
- conversation (compose DNS via this forwarder).

Important: use half-close (SHUT_WR) per direction. Closing both sockets when
one side EOFs truncates large chunked/SSE MCP responses (e.g. mcp-atlassian
tools/list) and surfaces as "SSE stream ended without a response".
"""
from __future__ import annotations

import errno
import socket
import sys
import threading


def _pipe_one(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            try:
                data = src.recv(65536)
            except OSError:
                break
            if not data:
                break
            try:
                dst.sendall(data)
            except OSError:
                break
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _handle(client: socket.socket, remote_host: str, remote_port: int) -> None:
    try:
        upstream = socket.create_connection((remote_host, remote_port), timeout=5)
    except OSError:
        client.close()
        return
    threads = [
        threading.Thread(target=_pipe_one, args=(client, upstream), daemon=True),
        threading.Thread(target=_pipe_one, args=(upstream, client), daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for s in (client, upstream):
        try:
            s.close()
        except OSError:
            pass


def serve(local_port: int, remote_host: str, remote_port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", local_port))
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(
                "[mcp-forward] 127.0.0.1:{} busy — skip".format(local_port),
                flush=True,
            )
            return
        raise
    sock.listen(64)
    print(
        "[mcp-forward] 127.0.0.1:{} → {}:{}".format(
            local_port, remote_host, remote_port
        ),
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
            "usage: {} <local_port> <remote_host> <remote_port>".format(sys.argv[0]),
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
