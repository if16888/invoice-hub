# -*- mode: python ; coding: utf-8 -*-
# ─────────────────────────────────────────────────────────────────────
# Invoice Hub — PyInstaller onedir spec (Windows x64)
# Target:  dist/InvoiceHub/InvoiceHub.exe
# Package: dist/InvoiceHub-windows-x64.zip
#
# Rules:
#   • onedir  — instant startup, no self-extraction overhead
#   • No UPX  — avoids Qt/PySide6 compatibility issues and loading delays
#   • No Playwright browser binaries bundled (B方案)
#   • Playwright driver is bundled
# ─────────────────────────────────────────────────────────────────────

import os
import sys
from pathlib import Path

# spec file lives under packaging/, so project root is one level up.
_here = Path(SPECPATH)          # noqa: F821  (SPECPATH is PyInstaller built-in)
_root = _here.parent

# ── Locate Playwright package ─────────────────────────────────────────
import playwright as _pw_mod
_pw_pkg = Path(_pw_mod.__file__).parent          # .../site-packages/playwright/
_pw_driver = _pw_pkg / "driver"                  # contains playwright.exe + node

# ── Data files to bundle ──────────────────────────────────────────────
_datas = [
    # App configuration template
    (str(_root / "config.example.json"), "."),
    # License and third-party notices must be present in release payloads.
    (str(_root / "LICENSE"), "."),
    (str(_root / "THIRD_PARTY_NOTICES.md"), "."),
    (str(_root / "licenses"), "licenses"),
    # GUI assets (logo, icons)
    (str(_root / "scripts" / "invoice_fetch" / "gui" / "assets"),
     "scripts/invoice_fetch/gui/assets"),
    # Playwright Python driver (playwright.exe + node.exe, ~100 MB)
    (str(_pw_driver), "playwright/driver"),
]

# ── Hidden imports ────────────────────────────────────────────────────
_hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtNetwork",
    "pdfplumber",
    "pdfminer",
    "pdfminer.high_level",
    "pdfminer.layout",
    "openpyxl",
    "keyring",
    "keyring.backends",
    "keyring.backends.Windows",
    "qrcode",
    "qrcode.image.pil",
    "PIL",
    "PIL.Image",
    "requests",
    "bs4",
    "cryptography",
    # Playwright async/sync API
    "playwright",
    "playwright.sync_api",
    "playwright.async_api",
    "playwright._impl._api_types",
    "playwright._impl._browser_type",
    "playwright._impl._playwright",
    "playwright._impl._driver",
    "greenlet",
]

# ── Exclusions ────────────────────────────────────────────────────────
_excludes = [
    "pytest",
    "unittest",
    "_pytest",
    "IPython",
    "jupyter",
    "notebook",
    "matplotlib",
    "scipy",
    "numpy",
    "pandas",
    "tkinter",
    "_tkinter",
]

_runtime_hooks = []

a = Analysis(                   # noqa: F821  (Analysis is PyInstaller built-in)
    [str(_root / "scripts" / "invoice_fetch_desktop.py")],
    pathex=[str(_root)],
    binaries=[],
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=_runtime_hooks,
    excludes=_excludes,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)               # noqa: F821  (PYZ is PyInstaller built-in)

exe = EXE(                      # noqa: F821  (EXE is PyInstaller built-in)
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,       # onedir: binaries go into COLLECT
    name="InvoiceHub",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                   # No UPX — prevents Qt load-time issues
    console=False,               # Windowed GUI, no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(                 # noqa: F821  (COLLECT is PyInstaller built-in)
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="InvoiceHub",           # → dist/InvoiceHub/
)
