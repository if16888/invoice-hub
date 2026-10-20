"""Local filtering proxy used by the link-downloader browser.

Playwright's route interception never sees redirect hops, and the ``request``
event only observes a request as it is being sent — a mail link can therefore
reach an intranet address before any guard reacts. This proxy closes that gap
at the network layer: the browser sends every request through it, each
connection (including each redirect hop, which opens a fresh connection) is
resolved and vetted *before* it is opened, and the connection is then made to
the vetted address only. Pinning the address also closes DNS-rebinding
windows between the check and the connection.

Only plain TCP tunnelling (``CONNECT``) and single-request HTTP forwarding are
implemented; the proxy never sees TLS plaintext and holds no certificate.
"""

from __future__ import annotations

import hashlib
import logging
import select
import socket
import socketserver
import threading
import time
from urllib.parse import urlsplit

_log = logging.getLogger("invoice_fetch")


class _MalformedRequest(Exception):
    """The client sent a request this proxy cannot forward safely."""


class _BodyTooLarge(Exception):
    """The request body exceeds the proxy's forwarding budget."""

_HEADER_LIMIT_BYTES = 64 * 1024
_BODY_LIMIT_BYTES = 8 * 1024 * 1024
_IDLE_TUNNEL_SECONDS = 30.0
_REJECT_REASONS = {
    400: b"Bad Request",
    403: b"Forbidden",
    413: b"Payload Too Large",
    503: b"Service Unavailable",
}


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


class SafeBrowserProxy:
    """Threaded HTTP proxy that only forwards to vetted public addresses.

    ``resolver(host, port)`` must return the exact address to connect to, or
    ``None`` to deny the host. Denied attempts are counted and fingerprinted
    (host names never enter the log) so callers and tests can assert on them.
    """

    def __init__(
        self,
        resolver,
        *,
        host: str = "127.0.0.1",
        header_timeout: float = 15.0,
        connect_timeout: float = 10.0,
        idle_timeout: float = 120.0,
        max_connections: int = 64,
    ):
        if not callable(resolver):
            raise TypeError("resolver must be callable")
        self.resolver = resolver
        self.header_timeout = float(header_timeout)
        self.connect_timeout = float(connect_timeout)
        self.idle_timeout = max(0.05, float(idle_timeout))
        self._host = host
        self._slots = threading.BoundedSemaphore(max(1, int(max_connections)))
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None
        self._tunnels_lock = threading.Lock()
        self._active_sockets: set[socket.socket] = set()
        self.blocked_count = 0
        self.blocked_fingerprints: list[str] = []

    @property
    def server_url(self) -> str:
        if self._server is None:
            raise RuntimeError("browser safety proxy is not running")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> str:
        if self._server is not None:
            return self.server_url
        try:
            server = socketserver.ThreadingTCPServer(
                (self._host, 0),
                _ProxyHandler,
                bind_and_activate=False,
            )
            server.daemon_threads = True
            server.allow_reuse_address = True
            server.proxy = self  # type: ignore[attr-defined]
            server.server_bind()
            server.server_activate()
        except OSError:
            try:
                server.server_close()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            raise
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name="InvoiceHubBrowserProxy",
            daemon=True,
        )
        self._thread.start()
        return self.server_url

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        self._close_active_tunnels()
        if server is not None:
            try:
                server.shutdown()
            finally:
                server.server_close()
        if thread is not None:
            thread.join(timeout=2.0)

    def _register_tunnel(self, *sockets_to_track: socket.socket) -> bool:
        """Track tunnel sockets; close them now if the proxy already stopped."""
        with self._tunnels_lock:
            stopped = self._server is None
            if not stopped:
                self._active_sockets.update(sockets_to_track)
        if stopped:
            for sock in sockets_to_track:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            return False
        return True

    def _unregister_tunnel(self, *sockets_to_track: socket.socket) -> None:
        with self._tunnels_lock:
            self._active_sockets.difference_update(sockets_to_track)

    def _close_active_tunnels(self) -> None:
        """Wake and terminate every tunnel so stop() leaves no lingering links."""
        with self._tunnels_lock:
            active = list(self._active_sockets)
            self._active_sockets.clear()
        for sock in active:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def __enter__(self) -> "SafeBrowserProxy":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def _acquire_slot(self) -> bool:
        return self._slots.acquire(blocking=False)

    def _release_slot(self) -> None:
        try:
            self._slots.release()
        except ValueError:
            pass

    def _record_blocked(self, host: str) -> None:
        fingerprint = _fingerprint(str(host or ""))
        self.blocked_count += 1
        if len(self.blocked_fingerprints) < 64:
            self.blocked_fingerprints.append(fingerprint)
        _log.warning("Browser safety proxy denied non-public host: <%s>", fingerprint)


class _ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        proxy: SafeBrowserProxy = self.server.proxy  # type: ignore[attr-defined]
        if not proxy._acquire_slot():
            self._reject(503)
            return
        try:
            client = self.request
            client.settimeout(proxy.header_timeout)
            header, body_prefix = self._read_header(client)
            if header is None:
                return
            request_line = header.split(b"\r\n", 1)[0].decode("iso-8859-1", errors="replace")
            parts = request_line.split(" ")
            if len(parts) < 2:
                self._reject(400)
                return
            method = parts[0].upper()
            target = parts[1]
            if method == "CONNECT":
                self._handle_connect(proxy, target)
            elif target.lower().startswith("http://"):
                self._handle_absolute_http(proxy, method, target, header, body_prefix)
            else:
                # Origin-form traffic and https absolute-form never arrive from
                # a browser; only proxy-shaped requests are accepted.
                self._reject(400)
        except Exception as exc:
            _log.debug("Browser safety proxy connection failed: %s", type(exc).__name__)
        finally:
            proxy._release_slot()
            try:
                self.request.close()
            except OSError:
                pass

    def _read_header(self, client) -> tuple[bytes | None, bytes]:
        data = b""
        while b"\r\n\r\n" not in data:
            if len(data) > _HEADER_LIMIT_BYTES:
                return None, b""
            chunk = client.recv(4096)
            if not chunk:
                return None, b""
            data += chunk
        header, _, rest = data.partition(b"\r\n\r\n")
        return header + b"\r\n\r\n", rest

    def _reject(self, code: int) -> None:
        reason = _REJECT_REASONS.get(code, b"Error")
        try:
            self.request.sendall(
                b"HTTP/1.1 " + str(int(code)).encode() + b" " + reason + b"\r\n"
                b"Content-Length: 0\r\nConnection: close\r\n\r\n"
            )
        except OSError:
            pass

    def _resolve(self, proxy: SafeBrowserProxy, host: str, port: int) -> str | None:
        try:
            address = proxy.resolver(host, port)
        except Exception:
            address = None
        if not address:
            proxy._record_blocked(host)
            return None
        return str(address)

    def _handle_connect(self, proxy: SafeBrowserProxy, target: str) -> None:
        host, _, port_text = target.rpartition(":")
        if not host:
            host, port_text = target, "443"
        try:
            port = int(port_text)
        except ValueError:
            self._reject(400)
            return
        address = self._resolve(proxy, host, port)
        if address is None:
            self._reject(403)
            return
        try:
            upstream = socket.create_connection((address, port), timeout=proxy.connect_timeout)
        except OSError:
            self._reject(503)
            return
        try:
            # Register before acknowledging CONNECT: stop() must see the tunnel
            # even if it lands immediately after the client received 200.
            if not proxy._register_tunnel(self.request, upstream):
                return
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            try:
                self._pump(self.request, upstream, proxy.idle_timeout)
            finally:
                proxy._unregister_tunnel(self.request, upstream)
        finally:
            try:
                upstream.close()
            except OSError:
                pass

    def _handle_absolute_http(
        self,
        proxy: SafeBrowserProxy,
        method: str,
        target: str,
        header: bytes,
        body_prefix: bytes,
    ) -> None:
        parsed = urlsplit(target)
        host = parsed.hostname or ""
        try:
            port = parsed.port or 80
        except ValueError:
            self._reject(400)
            return
        address = self._resolve(proxy, host, port)
        if address is None:
            self._reject(403)
            return

        header_lines = header.split(b"\r\n")
        content_length: int | None = None
        transfer_chunked = False
        for raw_line in header_lines[1:]:
            name, _, value = raw_line.partition(b":")
            key = name.strip().lower()
            if key == b"content-length":
                try:
                    content_length = int(value.strip())
                except ValueError:
                    content_length = 0
            elif key == b"transfer-encoding" and b"chunked" in value.lower():
                transfer_chunked = True
        if content_length is not None and content_length > _BODY_LIMIT_BYTES:
            self._reject(413)
            return
        if transfer_chunked:
            try:
                body = self._read_chunked_body(self.request, body_prefix)
            except _BodyTooLarge:
                self._reject(413)
                return
            except _MalformedRequest:
                self._reject(400)
                return
            content_length = len(body)
        else:
            body = body_prefix
            wanted = content_length or 0
            while len(body) < wanted:
                chunk = self.request.recv(min(65536, wanted - len(body)))
                if not chunk:
                    break
                body += chunk

        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        forwarded = [f"{method} {path} HTTP/1.1"]
        for raw_line in header_lines[1:]:
            if not raw_line:
                continue
            name = raw_line.split(b":", 1)[0].strip().lower()
            if name in {b"host", b"connection", b"proxy-connection", b"transfer-encoding", b"content-length"}:
                continue
            forwarded.append(raw_line.decode("iso-8859-1", errors="replace"))
        forwarded.append(f"Host: {host}" + (f":{port}" if port != 80 else ""))
        if content_length is not None:
            forwarded.append(f"Content-Length: {content_length}")
        forwarded.append("Connection: close")
        payload = "\r\n".join(forwarded).encode("iso-8859-1") + b"\r\n\r\n" + body[: content_length or 0]

        try:
            upstream = socket.create_connection((address, port), timeout=proxy.connect_timeout)
        except OSError:
            self._reject(503)
            return
        try:
            upstream.sendall(payload)
            upstream.settimeout(proxy.idle_timeout)
            while True:
                chunk = upstream.recv(65536)
                if not chunk:
                    return
                self.request.sendall(chunk)
        except OSError:
            return
        finally:
            try:
                upstream.close()
            except OSError:
                pass

    def _read_chunked_body(self, client, prefix: bytes) -> bytes:
        """De-chunk a request body so the forwarded request carries a length."""
        pending = bytearray(prefix)
        body = bytearray()

        def read_line() -> bytes:
            nonlocal pending
            while b"\r\n" not in pending:
                chunk = client.recv(4096)
                if not chunk:
                    raise _MalformedRequest
                pending += chunk
                if len(pending) > _HEADER_LIMIT_BYTES:
                    raise _MalformedRequest
            line, _, rest = bytes(pending).partition(b"\r\n")
            pending = bytearray(rest)
            return line

        while True:
            size_text = read_line().split(b";", 1)[0].strip()
            try:
                size = int(size_text, 16)
            except ValueError as exc:
                raise _MalformedRequest from exc
            if size == 0:
                # Trailer headers are consumed until the terminating blank line.
                while True:
                    trailer = read_line()
                    if trailer == b"":
                        return bytes(body)
            while len(pending) < size + 2:
                chunk = client.recv(4096)
                if not chunk:
                    raise _MalformedRequest
                pending += chunk
            body += pending[:size]
            del pending[: size + 2]
            if len(body) > _BODY_LIMIT_BYTES:
                raise _BodyTooLarge

    @staticmethod
    def _pump(left, right, idle_timeout: float = _IDLE_TUNNEL_SECONDS) -> None:
        peers = [left, right]
        last_activity = time.monotonic()
        try:
            while True:
                readable, _, _ = select.select(peers, [], [], min(5.0, idle_timeout))
                if not readable:
                    if time.monotonic() - last_activity >= idle_timeout:
                        return
                    continue
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    last_activity = time.monotonic()
                    (right if source is left else left).sendall(data)
        except OSError:
            return
