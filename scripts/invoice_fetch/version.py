"""Central Invoice Hub version metadata."""

from __future__ import annotations

import os
import re

from ._embedded_build_version import BUILD_VERSION as EMBEDDED_BUILD_VERSION

VERSION = "0.1.8"
PREVIOUS_STABLE_VERSION = "0.1.7"

_BUILD_VERSION_PATTERN = re.compile(
    rf"^(?P<base>{re.escape(VERSION)})(?P<suffix>-(?:rc|pre)\d+)?$"
)


def validate_build_version(candidate: str) -> str:
    """Validate a build/display version against the source release line."""
    value = str(candidate or "").strip()
    if not _BUILD_VERSION_PATTERN.fullmatch(value):
        raise ValueError(
            f"Build version must be {VERSION} or {VERSION}-rcN/{VERSION}-preN."
        )
    return value


def resolve_build_version(
    candidate: str | None = None,
    *,
    strict: bool = False,
) -> str:
    """Resolve the build display version without relying on Git at import time.

    Release builds embed their display version in the package before freezing.
    An explicit environment override remains useful for CI validation and
    development. Invalid non-strict values fall back to the source VERSION.
    """
    if candidate is None:
        raw_value = os.environ.get("INVOICE_HUB_BUILD_VERSION")
        if raw_value is None or not str(raw_value).strip():
            raw_value = EMBEDDED_BUILD_VERSION
    else:
        raw_value = candidate

    if raw_value is None or not str(raw_value).strip():
        return VERSION
    try:
        return validate_build_version(str(raw_value))
    except ValueError:
        if strict:
            raise
        return VERSION


BUILD_VERSION = resolve_build_version()
APP_VERSION = f"v{BUILD_VERSION}"
