# -*- coding: utf-8 -*-
"""
Standalone launcher for the Invoice Hub desktop application.

This module serves as the primary entry-point for the PyInstaller onedir build.
It delegates to the standard CLI main() function, injecting the desktop
sub-command when the user launches the executable directly (no arguments given).

Usage (development):
    python scripts/invoice_fetch_desktop.py
    python scripts/invoice_fetch_desktop.py desktop --startup-probe
"""

import os
import sys

# Ensure the project root is on the path when executed directly as a script
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from scripts.invoice_fetch.version import write_build_version_probe  # noqa: E402

_VERSION_PROBE_FLAG = "--version-probe-file"


def _run_version_probe_if_requested(argv: list[str]) -> bool:
    """Handle the private frozen-build probe before importing the GUI CLI."""
    if _VERSION_PROBE_FLAG not in argv[1:]:
        return False
    if len(argv) != 3 or argv[1] != _VERSION_PROBE_FLAG:
        raise SystemExit(2)
    output_path = argv[2]
    if not os.path.isabs(output_path):
        raise SystemExit(2)
    try:
        write_build_version_probe(output_path)
    except (OSError, TypeError, ValueError):
        raise SystemExit(1) from None
    return True


if __name__ == "__main__":
    if _run_version_probe_if_requested(sys.argv):
        raise SystemExit(0)

    from scripts.invoice_fetch.__main__ import main

    # Default to the GUI when no arguments are supplied.
    if len(sys.argv) == 1:
        sys.argv.append("desktop")
    main()
