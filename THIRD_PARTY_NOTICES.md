# Third-Party Notices

Invoice Hub is distributed under the Apache License 2.0. It also uses
third-party open-source components. This notice is informational and does not
replace the license texts distributed by those projects.

## Runtime Dependencies

| Component | Use | License summary |
|---|---|---|
| PySide6 / Qt for Python | Desktop GUI, PDF preview, network interface helpers | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only, with commercial licensing available from Qt |
| Shiboken6 | PySide6 binding support | LGPL/GPL/commercial Qt licensing family |
| Playwright Python and driver | Browser-assisted invoice download using an installed Edge/Chrome/Chromium channel | Apache-2.0 for Playwright package and bundled driver files |
| pdfplumber / pdfminer.six | Local PDF text extraction | MIT-style licenses |
| openpyxl | Excel workbook generation | MIT |
| requests | HTTP client utilities | Apache-2.0 |
| beautifulsoup4 | HTML parsing | MIT |
| keyring | OS credential-store integration | MIT |
| qrcode / Pillow | Local QR upload page support | BSD-style / HPND-style licenses |
| cryptography | Secure primitives used by dependencies/keyring backends | Apache-2.0 OR BSD-3-Clause |
| PyInstaller | Windows one-dir packaging | GPLv2-or-later with PyInstaller exception |
| Inno Setup | Optional Windows installer generation | Inno Setup license |

## Qt / PySide6 Dynamic Linking Note

Invoice Hub uses PySide6 dynamically as provided by the Python wheels and the
PyInstaller one-dir build. The project does not modify Qt or PySide6 source
code and does not statically link Qt libraries.

Users may obtain Qt and Qt for Python source and license information from:

- https://www.qt.io/download
- https://doc.qt.io/qtforpython-6/
- https://www.qt.io/licensing/open-source-lgpl-obligations

## Packaged License Files

PyInstaller includes many package `.dist-info` license files in the built
application directory. Release maintainers should verify that `LICENSE` and
`THIRD_PARTY_NOTICES.md` are included at the root of the portable package and
installer payload.

## Browser Binaries

Invoice Hub does not bundle Playwright Chromium browser binaries. Browser
download automation uses an installed Microsoft Edge, Google Chrome, or a user
managed Playwright Chromium installation.
