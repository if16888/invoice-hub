"""Tests for the public export hygiene checker."""

from __future__ import annotations

import tempfile
import subprocess
import unittest
from pathlib import Path

from scripts.check_public_export import find_public_export_issues, find_source_tree_issues, main


REQUIRED_PUBLIC_FILES = (
    ".github/CODEOWNERS",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/user-quickstart.md",
    "docs/privacy-and-feedback.md",
    "docs/privacy-data-flow.md",
    "docs/release-checklist.md",
)


def _write_minimal_public_tree(root: Path) -> None:
    for rel in REQUIRED_PUBLIC_FILES:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic public file\n", encoding="utf-8")


class TestPublicExportCheck(unittest.TestCase):
    def test_clean_public_tree_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_public_tree(root)

            self.assertEqual(find_public_export_issues(root), [])

    def test_forbids_private_docs_and_runtime_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_public_tree(root)
            (root / "AGENTS.md").write_text("private agent notes\n", encoding="utf-8")
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "invoices.db").write_bytes(b"sqlite")
            claude_dir = root / ".claude"
            claude_dir.mkdir()
            (claude_dir / "settings.local.json").write_text("{}\n", encoding="utf-8")

            issues = "\n".join(find_public_export_issues(root))

            self.assertIn("forbidden file: AGENTS.md", issues)
            self.assertIn("forbidden directory: runtime", issues)
            self.assertIn("file under forbidden directory: runtime/invoices.db", issues)
            self.assertIn("forbidden directory: .claude", issues)
            self.assertIn("file under forbidden directory: .claude/settings.local.json", issues)

    def test_requires_codeowners(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_public_tree(root)
            (root / ".github" / "CODEOWNERS").unlink()

            issues = "\n".join(find_public_export_issues(root))

            self.assertIn("missing required public file: .github/CODEOWNERS", issues)

    def test_forbids_secret_file_names_and_key_suffixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_public_tree(root)
            for rel in (
                ".env",
                ".env.local",
                ".npmrc",
                ".pypirc",
                "credentials.json",
                "secrets.json",
                "id_rsa",
                "id_ed25519",
                "cert.pem",
                "private.key",
                "identity.p12",
                "identity.pfx",
            ):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("synthetic secret\n", encoding="utf-8")

            issues = "\n".join(find_public_export_issues(root))

            self.assertIn("forbidden secret/config file name: .env", issues)
            self.assertIn("forbidden secret/config file name: credentials.json", issues)
            self.assertIn("forbidden secret/config file name: id_rsa", issues)
            self.assertIn("forbidden generated/private file type: cert.pem", issues)
            self.assertIn("forbidden generated/private file type: private.key", issues)
            self.assertIn("forbidden generated/private file type: identity.p12", issues)
            self.assertIn("forbidden generated/private file type: identity.pfx", issues)

    def test_allows_synthetic_fixtures_gui_assets_and_docs_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_public_tree(root)
            asset = root / "scripts" / "invoice_fetch" / "gui" / "assets" / "logo.png"
            docs_image = root / "docs" / "images" / "invoice-hub-overview.png"
            fixture = root / "tests" / "fixtures" / "synthetic" / "sample.pdf"
            asset.parent.mkdir(parents=True, exist_ok=True)
            docs_image.parent.mkdir(parents=True, exist_ok=True)
            fixture.parent.mkdir(parents=True, exist_ok=True)
            asset.write_bytes(b"synthetic image")
            docs_image.write_bytes(b"synthetic overview image")
            fixture.write_bytes(b"synthetic pdf")

            self.assertEqual(find_public_export_issues(root), [])

    def test_allows_vendored_pdfjs_runtime_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_public_tree(root)
            asset_root = root / "scripts" / "invoice_fetch" / "web_assets" / "pdfjs"
            asset_root.mkdir(parents=True, exist_ok=True)
            for name in (
                Path("pdf.min.mjs"),
                Path("pdf.worker.min.mjs"),
                Path("cmaps") / "CMap.bcmap",
                Path("standard_fonts") / "FoxitSerif.pfb",
                Path("standard_fonts") / "LiberationSans.ttf",
            ):
                path = asset_root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic PDF.js asset")

            self.assertEqual(find_public_export_issues(root), [])

    def test_ignores_git_and_pycache_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_public_tree(root)
            git_dir = root / ".git"
            cache_dir = root / "scripts" / "__pycache__"
            git_dir.mkdir()
            cache_dir.mkdir(parents=True)
            (git_dir / "config").write_text("synthetic\n", encoding="utf-8")
            (cache_dir / "module.pyc").write_bytes(b"compiled")

            self.assertEqual(find_public_export_issues(root), [])

    def test_source_tree_rejects_tracked_release_risk_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_public_tree(root)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)

            risky_files = (
                root / "real_invoice.pdf",
                root / "reimbursement.xlsx",
                root / "config.json",
            )
            for path in risky_files:
                path.write_bytes(b"synthetic risky file")

            allowed_fixture = root / "tests" / "fixtures" / "synthetic" / "sample.pdf"
            allowed_fixture.parent.mkdir(parents=True, exist_ok=True)
            allowed_fixture.write_bytes(b"synthetic fixture")

            subprocess.run(
                [
                    "git",
                    "add",
                    "-f",
                    "real_invoice.pdf",
                    "reimbursement.xlsx",
                    "config.json",
                    "tests/fixtures/synthetic/sample.pdf",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )

            issues = "\n".join(find_source_tree_issues(root))

            self.assertIn("forbidden tracked release-risk file type: real_invoice.pdf", issues)
            self.assertIn("forbidden tracked release-risk file type: reimbursement.xlsx", issues)
            self.assertIn("forbidden tracked private/public-excluded file: config.json", issues)
            self.assertNotIn("tests/fixtures/synthetic/sample.pdf", issues)

    def test_source_tree_rejects_tracked_runtime_backups_even_if_gitignored_later(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_public_tree(root)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            backup = root / "runtime" / "backups" / "invoices-20260609-123456-before-test.db"
            backup.parent.mkdir(parents=True)
            backup.write_bytes(b"sqlite backup")
            subprocess.run(
                ["git", "add", "-f", *REQUIRED_PUBLIC_FILES, "runtime/backups/invoices-20260609-123456-before-test.db"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            (root / ".gitignore").write_text("runtime/\n", encoding="utf-8")

            issues = "\n".join(find_source_tree_issues(root))

            self.assertIn(
                "forbidden tracked file under generated/private directory: runtime/backups/invoices-20260609-123456-before-test.db",
                issues,
            )
            self.assertIn(
                "forbidden tracked release-risk file type: runtime/backups/invoices-20260609-123456-before-test.db",
                issues,
            )

    def test_source_tree_rejects_tracked_claude_state_even_if_gitignored_later(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_public_tree(root)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            claude_state = root / ".claude" / "settings.local.json"
            claude_state.parent.mkdir(parents=True)
            claude_state.write_text("{}\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "-f", *REQUIRED_PUBLIC_FILES, ".claude/settings.local.json"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            (root / ".gitignore").write_text(".claude/\n", encoding="utf-8")

            issues = "\n".join(find_source_tree_issues(root))

            self.assertIn(
                "forbidden tracked file under generated/private directory: .claude/settings.local.json",
                issues,
            )

    def test_public_checkout_ignores_untracked_runtime_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_public_tree(root)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            (root / ".gitignore").write_text("runtime/\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", ".gitignore", *REQUIRED_PUBLIC_FILES],
                cwd=root,
                check=True,
                capture_output=True,
            )

            runtime = root / "runtime"
            upload_dir = runtime / "inbox" / "mobile_upload" / "2026-06-01" / "mobile_20260601_153048_e2mY_b"
            upload_dir.mkdir(parents=True)
            (upload_dir / "manifest.json").write_text("{}", encoding="utf-8")
            (runtime / "invoices.db").write_bytes(b"sqlite")

            self.assertEqual(main([str(root)]), 0)


if __name__ == "__main__":
    unittest.main()
