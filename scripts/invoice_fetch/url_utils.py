"""URL helpers shared across CLI, GUI, and exports."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def _mask_url(url: str) -> str:
    """Mask query parameter values and strip fragments from a URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        query_params = parse_qsl(parsed.query, keep_blank_values=True)
        masked_query = urlencode([(k, "***") for k, _ in query_params], doseq=True) if query_params else ""
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                masked_query,
                "",
            )
        )
    except Exception:
        return url
