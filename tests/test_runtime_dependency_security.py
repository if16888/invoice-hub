"""Regression checks for the locked external-input dependency boundary.

These checks intentionally combine installed-package checks with source and
workflow provenance checks.  The former protects the runtime that executes
the tests; the latter prevents a future CI/release job from silently falling
back to floating requirements.
"""

from __future__ import annotations

import inspect
from importlib.metadata import version
from pathlib import Path
import unittest

from packaging.version import Version


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PKCS7_NAMES = (
    "pkcs7_decrypt_der",
    "pkcs7_decrypt_pem",
    "pkcs7_decrypt_smime",
    "load_der_pkcs7",
    "load_pem_pkcs7",
)


def _locked_version(lock_name: str, package_name: str) -> Version:
    """Read a normalized package version from a pip-compile lock file."""

    normalized = package_name.lower().replace("_", "-")
    for line in (PROJECT_ROOT / lock_name).read_text(encoding="utf-8").splitlines():
        if "==" not in line or line.lstrip().startswith("#"):
            continue
        candidate, pinned = (part.strip() for part in line.split("==", 1))
        if candidate.lower().replace("_", "-") == normalized:
            return Version(pinned)
    raise AssertionError(f"{package_name} is not pinned in {lock_name}")


class RuntimeDependencySecurityTests(unittest.TestCase):
    def test_installed_runtime_meets_security_floors(self):
        floors = {
            "pdfminer.six": "20251230",
            "Pillow": "12.3.0",
            "cryptography": "50.0.0",
        }
        for package_name, floor in floors.items():
            with self.subTest(package=package_name):
                self.assertGreaterEqual(Version(version(package_name)), Version(floor))

    def test_committed_runtime_lock_meets_security_floors(self):
        floors = {
            "pdfminer-six": "20251230",
            "pillow": "12.3.0",
            "cryptography": "50.0.0",
        }
        for package_name, floor in floors.items():
            with self.subTest(package=package_name):
                self.assertGreaterEqual(
                    _locked_version("requirements.lock.txt", package_name),
                    Version(floor),
                )

    def test_pdfminer_cmap_loader_has_no_pickle_loading_path(self):
        import pdfminer.cmapdb as cmapdb

        source = inspect.getsource(cmapdb.CMapDB._load_data).lower()
        self.assertIn("json.gz", source)
        self.assertIn("realpath", source)
        self.assertNotIn("pickle", source)

    def test_product_pdf_path_does_not_reach_cryptography_pkcs7(self):
        pdfdocument_source = inspect.getsource(__import__("pdfminer.pdfdocument", fromlist=["*"]))
        self.assertIn("Cipher", pdfdocument_source)
        self.assertFalse(
            any(name in pdfdocument_source for name in _PKCS7_NAMES),
            "pdfminer PDF encryption path unexpectedly exposes a PKCS#7 API",
        )

        for relative_path in (
            "scripts/invoice_fetch/invoice_parser.py",
            "scripts/invoice_fetch/__main__.py",
        ):
            source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
            with self.subTest(path=relative_path):
                self.assertIn("pdfplumber", source)
                self.assertFalse(any(name in source for name in _PKCS7_NAMES))

    def test_release_and_ci_use_committed_lock_inputs(self):
        workflow_paths = (
            PROJECT_ROOT / ".github/workflows/ci.yml",
            PROJECT_ROOT / ".github/workflows/windows-release.yml",
        )
        for workflow_path in workflow_paths:
            source = workflow_path.read_text(encoding="utf-8")
            with self.subTest(path=workflow_path.name):
                self.assertIn("requirements.lock.txt", source)
                self.assertIn("requirements-desktop.lock.txt", source)
                self.assertIn("requirements-build.lock.txt", source)
                self.assertNotIn("-r requirements.txt", source)
                self.assertNotIn("-r requirements-build.txt", source)

    def test_lock_inputs_remain_separated_by_runtime_role(self):
        self.assertIn("pyside6==", (PROJECT_ROOT / "requirements-desktop.lock.txt").read_text(encoding="utf-8"))
        self.assertIn("pyinstaller==", (PROJECT_ROOT / "requirements-build.lock.txt").read_text(encoding="utf-8"))
        self.assertGreaterEqual(
            _locked_version("requirements.lock.txt", "pdfplumber"),
            Version("0.11.10"),
        )


if __name__ == "__main__":
    unittest.main()
