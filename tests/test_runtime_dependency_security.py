"""Regression checks for the locked external-input dependency boundary.

These checks intentionally combine installed-package checks with source and
workflow provenance checks.  The former protects the runtime that executes
the tests; the latter prevents a future CI/release job from silently falling
back to floating requirements.
"""

from __future__ import annotations

import inspect
import re
from importlib.metadata import PackageNotFoundError, requires, version
from pathlib import Path
import unittest

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.version import Version


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PKCS7_NAMES = (
    "pkcs7_decrypt_der",
    "pkcs7_decrypt_pem",
    "pkcs7_decrypt_smime",
    "load_der_pkcs7",
    "load_pem_pkcs7",
)
_LOCK_FILES = (
    "requirements.lock.txt",
    "requirements-desktop.lock.txt",
    "requirements-build.lock.txt",
    "requirements-test.lock.txt",
)
# The locks are resolved for the Windows Python 3.11 baseline. Evaluate
# environment markers against that target so the closure check is identical
# on Windows CI and on a Linux development checkout.
_WINDOWS_MARKER_ENVIRONMENT = {
    **default_environment(),
    "sys_platform": "win32",
    "platform_system": "Windows",
    "os_name": "nt",
    "platform_machine": "AMD64",
    "python_version": "3.11",
    "python_full_version": "3.11.9",
    "implementation_name": "cpython",
    "platform_python_implementation": "CPython",
}


def _normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _locked_pins(lock_name: str) -> dict[str, tuple[str, Version]]:
    """Return normalized package name -> (display name, pinned version)."""

    pins: dict[str, tuple[str, Version]] = {}
    for line in (PROJECT_ROOT / lock_name).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "==" not in stripped:
            continue
        raw_name, raw_version = (part.strip() for part in stripped.split("==", 1))
        name = Requirement(raw_name).name
        pins[_normalize_package_name(name)] = (name, Version(raw_version))
    return pins


def _all_locked_pins() -> dict[str, tuple[str, Version]]:
    pins: dict[str, tuple[str, Version]] = {}
    for lock_name in _LOCK_FILES:
        for key, value in _locked_pins(lock_name).items():
            existing = pins.get(key)
            if existing is not None and existing[1] != value[1]:
                raise AssertionError(
                    f"{key} is pinned to both {existing[1]} and {value[1]} across lock files"
                )
            pins[key] = value
    return pins


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
    def test_desktop_qt_excludes_the_known_windows_native_exit_regression(self):
        inputs = [Requirement(line.strip()) for line in
                  (PROJECT_ROOT / "requirements-desktop.txt").read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.lstrip().startswith("#")]
        requirement = next(item for item in inputs if item.name.lower() == "pyside6")
        for incompatible in ("6.12.0", "6.12.1"):
            self.assertNotIn(Version(incompatible), requirement.specifier,
                             "Qt upgrades require a successful Windows native exit/HCI retest")
        qt = _locked_version("requirements-desktop.lock.txt", "pyside6")
        self.assertLess(qt, Version("6.12"))
        self.assertIn(qt, requirement.specifier)
        for dependency in ("pyside6-addons", "pyside6-essentials", "shiboken6"):
            self.assertEqual(_locked_version("requirements-desktop.lock.txt", dependency), qt)

    def test_installed_runtime_meets_security_floors(self):
        floors = {
            "pdfminer.six": "20251230",
            "Pillow": "13.0.0",
            "cryptography": "50.0.0",
            "urllib3": "2.8.0",
            "certifi": "2026.10.18",
        }
        for package_name, floor in floors.items():
            with self.subTest(package=package_name):
                self.assertGreaterEqual(Version(version(package_name)), Version(floor))

    def test_committed_runtime_lock_meets_security_floors(self):
        floors = {
            "pdfminer-six": "20251230",
            "pillow": "13.0.0",
            "cryptography": "50.0.0",
            "urllib3": "2.8.0",
            "certifi": "2026.10.18",
        }
        for package_name, floor in floors.items():
            with self.subTest(package=package_name):
                self.assertGreaterEqual(
                    _locked_version("requirements.lock.txt", package_name),
                    Version(floor),
                )

    def test_committed_build_lock_meets_security_floors(self):
        self.assertGreaterEqual(
            _locked_version("requirements-build.lock.txt", "setuptools"),
            Version("84.1.0"),
        )

    def test_source_urllib3_requirement_excludes_vulnerable_versions(self):
        requirements = [
            Requirement(line.strip())
            for line in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        requirement = next(item for item in requirements if item.name.lower() == "urllib3")
        for vulnerable in ("1.26.20", "2.6.2", "2.7.0"):
            with self.subTest(version=vulnerable):
                self.assertNotIn(Version(vulnerable), requirement.specifier)
        self.assertIn(Version("2.8.0"), requirement.specifier)
        self.assertIn(_locked_version("requirements.lock.txt", "urllib3"), requirement.specifier)

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
            "scripts/invoice_fetch/pdf_boundary.py",
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


class LockedDependencyClosureTests(unittest.TestCase):
    def test_windows_dependency_closure_is_fully_pinned(self):
        pins = _all_locked_pins()
        unavailable: list[str] = []
        missing: list[str] = []
        unsatisfied: list[str] = []

        for package_name, pinned in sorted(pins.values(), key=lambda item: item[0].lower()):
            try:
                declared = requires(package_name) or ()
            except PackageNotFoundError:
                unavailable.append(package_name)
                continue
            for raw_requirement in declared:
                requirement = Requirement(raw_requirement)
                if requirement.marker is not None and not requirement.marker.evaluate(
                    {**_WINDOWS_MARKER_ENVIRONMENT, "extra": ""}
                ):
                    continue
                target = pins.get(_normalize_package_name(requirement.name))
                if target is None:
                    missing.append(f"{package_name} {pinned} requires {requirement}")
                elif target[1] not in requirement.specifier:
                    unsatisfied.append(
                        f"{package_name} {pinned} requires {requirement}; "
                        f"the lock has {target[0]} {target[1]}"
                    )

        self.assertEqual(
            unavailable,
            [],
            "the environment is missing locked packages; install all four lock files",
        )
        self.assertEqual(missing, [], "the lock closure is missing dependencies")
        self.assertEqual(
            unsatisfied,
            [],
            "locked versions do not satisfy declared dependencies",
        )

    def test_source_requirements_are_pinned_by_their_lock(self):
        pairs = (
            ("requirements.txt", "requirements.lock.txt"),
            ("requirements-desktop.txt", "requirements-desktop.lock.txt"),
            ("requirements-build.txt", "requirements-build.lock.txt"),
            ("requirements-test.txt", "requirements-test.lock.txt"),
        )
        for source_name, lock_name in pairs:
            pins = _locked_pins(lock_name)
            for line in (PROJECT_ROOT / source_name).read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                requirement = Requirement(stripped)
                with self.subTest(source=source_name, package=requirement.name):
                    target = pins.get(_normalize_package_name(requirement.name))
                    self.assertIsNotNone(target, f"{requirement.name} is missing from {lock_name}")
                    self.assertIn(target[1], requirement.specifier)


if __name__ == "__main__":
    unittest.main()
