"""Unit tests for the local filtering proxy used by the invoice browser."""

from __future__ import annotations

import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scripts.invoice_fetch.browser_proxy import SafeBrowserProxy


class _TrapListener:
    """Raw TCP listener that counts every accepted connection."""

    def __init__(self):
        self.accepts = 0
        self._server = socket.socket()
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(4)
        self.port = self._server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            self.accepts += 1
            try:
                conn.close()
            except OSError:
                pass

    def close(self):
        self._server.close()


class _EchoServer:
    """Raw TCP echo server for CONNECT tunnel tests."""

    def __init__(self):
        self._server = socket.socket()
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(4)
        self.port = self._server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._echo, args=(conn,), daemon=True).start()

    @staticmethod
    def _echo(conn):
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    return
                conn.sendall(b"echo:" + data)
        except OSError:
            return
        finally:
            conn.close()

    def close(self):
        self._server.close()


def _proxy_client(proxy_url: str) -> socket.socket:
    host, _, port = proxy_url.partition("://")[2].partition(":")
    client = socket.create_connection((host, int(port)), timeout=5)
    client.settimeout(5)
    return client


def _read_until_close(client: socket.socket, limit: int = 65536) -> bytes:
    data = b""
    while len(data) < limit:
        chunk = client.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


class SafeBrowserProxyTests(unittest.TestCase):
    def _start_proxy(self, resolver) -> SafeBrowserProxy:
        proxy = SafeBrowserProxy(resolver)
        proxy.start()
        self.addCleanup(proxy.stop)
        return proxy

    def test_connect_tunnel_uses_the_vetted_address(self):
        echo = _EchoServer()
        self.addCleanup(echo.close)
        calls: list[tuple[str, int]] = []

        def resolver(host, port):
            calls.append((host, port))
            return "127.0.0.1" if host == "allowed.test" else None

        proxy = self._start_proxy(resolver)
        client = _proxy_client(proxy.server_url)
        self.addCleanup(client.close)

        client.sendall(
            f"CONNECT allowed.test:{echo.port} HTTP/1.1\r\nHost: allowed.test:{echo.port}\r\n\r\n".encode()
        )
        head = client.recv(4096)
        self.assertIn(b"200 Connection Established", head)

        client.sendall(b"ping")
        self.assertEqual(client.recv(64), b"echo:ping")
        self.assertEqual(calls[0], ("allowed.test", echo.port))

    def test_connect_to_denied_host_is_rejected_without_any_connection(self):
        trap = _TrapListener()
        self.addCleanup(trap.close)

        proxy = self._start_proxy(lambda host, port: None)
        client = _proxy_client(proxy.server_url)
        self.addCleanup(client.close)

        client.sendall(
            f"CONNECT internal.test:{trap.port} HTTP/1.1\r\nHost: internal.test:{trap.port}\r\n\r\n".encode()
        )
        response = _read_until_close(client)
        self.assertIn(b"403 Forbidden", response)
        self.assertEqual(trap.accepts, 0)
        self.assertEqual(proxy.blocked_count, 1)
        self.assertEqual(len(proxy.blocked_fingerprints), 1)

    def test_absolute_get_is_forwarded_with_the_original_host_header(self):
        seen: dict[str, str] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen["host"] = self.headers.get("Host", "")
                seen["path"] = self.path
                seen["connection"] = self.headers.get("Connection", "")
                body = b"live"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (upstream.shutdown(), upstream.server_close()))
        upstream_port = upstream.server_address[1]

        def resolver(host, port):
            return "127.0.0.1" if host == "allowed.test" else None

        proxy = self._start_proxy(resolver)
        client = _proxy_client(proxy.server_url)
        self.addCleanup(client.close)

        client.sendall(
            f"GET http://allowed.test:{upstream_port}/hello?x=1 HTTP/1.1\r\n"
            f"Host: allowed.test:{upstream_port}\r\n"
            "Proxy-Connection: keep-alive\r\n\r\n".encode()
        )
        response = _read_until_close(client)
        self.assertIn(b"200", response.split(b"\r\n", 1)[0])
        self.assertIn(b"live", response)
        self.assertEqual(seen.get("host"), f"allowed.test:{upstream_port}")
        self.assertEqual(seen.get("path"), "/hello?x=1")
        self.assertEqual(seen.get("connection"), "close")

    def test_absolute_request_to_denied_host_is_403(self):
        trap = _TrapListener()
        self.addCleanup(trap.close)

        proxy = self._start_proxy(lambda host, port: None)
        client = _proxy_client(proxy.server_url)
        self.addCleanup(client.close)

        client.sendall(
            f"GET http://internal.test:{trap.port}/secret HTTP/1.1\r\n"
            f"Host: internal.test:{trap.port}\r\n\r\n".encode()
        )
        response = _read_until_close(client)
        self.assertIn(b"403 Forbidden", response)
        self.assertEqual(trap.accepts, 0)

    def test_origin_form_request_is_rejected(self):
        proxy = self._start_proxy(lambda host, port: None)
        client = _proxy_client(proxy.server_url)
        self.addCleanup(client.close)

        client.sendall(b"GET /local HTTP/1.1\r\nHost: local\r\n\r\n")
        response = _read_until_close(client)
        self.assertIn(b"400 Bad Request", response)

    def test_chunked_request_body_is_forwarded_with_content_length(self):
        seen: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                seen["body"] = self.rfile.read(length)
                seen["transfer_encoding"] = self.headers.get("Transfer-Encoding", "")
                seen["content_length"] = length
                body = b"ok"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (upstream.shutdown(), upstream.server_close()))
        upstream_port = upstream.server_address[1]

        proxy = self._start_proxy(
            lambda host, port: "127.0.0.1" if host == "allowed.test" else None,
        )
        client = _proxy_client(proxy.server_url)
        self.addCleanup(client.close)

        client.sendall(
            (
                f"POST http://allowed.test:{upstream_port}/upload HTTP/1.1\r\n"
                f"Host: allowed.test:{upstream_port}\r\n"
                "Transfer-Encoding: chunked\r\n\r\n"
                "5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n"
            ).encode()
        )
        response = _read_until_close(client)
        self.assertIn(b"200", response.split(b"\r\n", 1)[0])
        self.assertEqual(seen.get("body"), b"hello world")
        self.assertEqual(seen.get("content_length"), 11)
        self.assertEqual(seen.get("transfer_encoding"), "")

    def test_idle_tunnel_is_closed_by_the_idle_timeout(self):
        echo = _EchoServer()
        self.addCleanup(echo.close)
        proxy = SafeBrowserProxy(
            lambda host, port: "127.0.0.1", idle_timeout=0.2,
        )
        proxy.start()
        self.addCleanup(proxy.stop)

        client = _proxy_client(proxy.server_url)
        self.addCleanup(client.close)
        client.sendall(
            f"CONNECT allowed.test:{echo.port} HTTP/1.1\r\nHost: allowed.test:{echo.port}\r\n\r\n".encode()
        )
        self.assertIn(b"200 Connection Established", client.recv(4096))

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                data = client.recv(64)
            except socket.timeout:
                continue
            if data == b"":
                break
        else:  # pragma: no cover - guard against a leaked tunnel
            self.fail("idle tunnel stayed open")

    def test_stop_closes_an_active_tunnel(self):
        echo = _EchoServer()
        self.addCleanup(echo.close)
        proxy = self._start_proxy(lambda host, port: "127.0.0.1")

        client = _proxy_client(proxy.server_url)
        self.addCleanup(client.close)
        client.sendall(
            f"CONNECT allowed.test:{echo.port} HTTP/1.1\r\nHost: allowed.test:{echo.port}\r\n\r\n".encode()
        )
        self.assertIn(b"200 Connection Established", client.recv(4096))

        proxy.stop()
        self.assertEqual(client.recv(64), b"")

    def test_start_and_stop_are_idempotent(self):
        proxy = SafeBrowserProxy(lambda host, port: None)
        first = proxy.start()
        second = proxy.start()
        self.assertEqual(first, second)
        proxy.stop()
        proxy.stop()

    def test_server_recovers_after_a_client_disconnect(self):
        echo = _EchoServer()
        self.addCleanup(echo.close)
        proxy = self._start_proxy(lambda host, port: "127.0.0.1")

        abandoned = _proxy_client(proxy.server_url)
        abandoned.sendall(
            f"CONNECT allowed.test:{echo.port} HTTP/1.1\r\nHost: allowed.test:{echo.port}\r\n\r\n".encode()
        )
        abandoned.recv(4096)
        abandoned.close()

        healthy = _proxy_client(proxy.server_url)
        self.addCleanup(healthy.close)
        healthy.sendall(
            f"CONNECT allowed.test:{echo.port} HTTP/1.1\r\nHost: allowed.test:{echo.port}\r\n\r\n".encode()
        )
        self.assertIn(b"200 Connection Established", healthy.recv(4096))
        healthy.sendall(b"ping")
        self.assertEqual(healthy.recv(64), b"echo:ping")


if __name__ == "__main__":
    unittest.main()
