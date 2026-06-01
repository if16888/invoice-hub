# -*- coding: utf-8 -*-
"""
Invoice Hub Desktop Application Launcher
"""
import sys
from scripts.invoice_fetch.__main__ import main

if __name__ == "__main__":
    # If launched with no arguments, default to launching the desktop GUI
    if len(sys.argv) == 1:
        sys.argv.append("desktop")
    main()
