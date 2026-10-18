"""Windows-safe file-name helpers shared by attachment, download, and upload paths.

File names in this project can originate from untrusted places: mail attachment
names, downloaded ``Content-Disposition`` names, and phone-upload names. Windows
rejects some names that POSIX accepts — reserved device names (``CON``, ``NUL``,
``COM1``…), control characters, and trailing dots or spaces — so every name that
reaches the filesystem goes through the helpers here.
"""

from __future__ import annotations

import re

# Characters Windows rejects inside a file-name component, including the
# C0/C1 control ranges.
WINDOWS_ILLEGAL_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f-\x9f]')

# Reserved device names Windows cannot use as a file stem (case-insensitive),
# including the superscript digits some Windows APIs report.
WINDOWS_RESERVED_STEM_RE = re.compile(
    r"(?i)^(?:CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])$"
)


def escape_windows_reserved_stem(stem: str, *, prefix: str = "_") -> str:
    """Prefix reserved device names so the file can exist on Windows.

    The check applies to the portion before the first dot, matching how
    Windows interprets ``CON.pdf`` as a device name rather than a file.
    """
    head = str(stem or "").split(".", 1)[0].rstrip(". ")
    if head and WINDOWS_RESERVED_STEM_RE.match(head):
        return f"{prefix}{stem}"
    return stem


def sanitize_windows_basename(name: str, *, fallback: str = "untitled") -> str:
    """Return a Windows-safe basename for an untrusted name.

    Only the last path component is kept, illegal and control characters are
    replaced with underscores, trailing dots/spaces are trimmed, and reserved
    device names are escaped. An empty result falls back to *fallback*
    (``""`` keeps the empty result so callers can supply their own fallback).
    """
    candidate = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    candidate = WINDOWS_ILLEGAL_CHARS_RE.sub("_", candidate)
    candidate = candidate.strip(" .")
    if not candidate or candidate in {".", ".."}:
        candidate = fallback
    return escape_windows_reserved_stem(candidate)
