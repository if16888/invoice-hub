"""URL helpers shared across CLI, GUI, and exports."""

from __future__ import annotations

from urllib.parse import urlparse


def _mask_url(url: str) -> str:
    """Keep only the public origin; paths may also contain access tokens."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "<url:redacted>"
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"{parsed.scheme}://{host}{port}/<redacted>"
    except Exception:
        return "<url:redacted>"
