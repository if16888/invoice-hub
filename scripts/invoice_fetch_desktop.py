# -*- coding: utf-8 -*-
"""
Standalone launcher for the Invoice Hub desktop application.

This module serves as the primary entry-point for the PyInstaller onedir build.
It delegates to the standard CLI ``main()`` function, injecting the ``desktop``
sub-command when the user launches the executable directly (no arguments given).

Usage (development):
    python scripts/invoice_fetch_desktop.py
    python scripts/invoice_fetch_desktop.py desktop --startup-probe
"""

import sys
import os

# Ensure the project root is on the path when executed directly as a script
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from scripts.invoice_fetch.__main__ import main  # noqa: E402

if __name__ == "__main__":
    # Default to the GUI when no sub-command is supplied.
    if len(sys.argv) == 1:
        sys.argv.append("desktop")
    main()
