from pathlib import Path

import pytest

from scripts.invoice_fetch.export_paths import (
    default_export_directory,
    migrate_legacy_exports,
    resolve_export_directory,
)


def test_default_export_path_is_user_documents_not_install_dir(tmp_path):
    install = tmp_path / "Program Files" / "InvoiceHub"
    target = default_export_directory(tmp_path / "Documents")
    assert target == tmp_path / "Documents" / "Invoice Hub" / "Exports"
    assert install not in target.parents


def test_custom_export_path_is_preserved(tmp_path):
    custom = tmp_path / "chosen" / "packages"
    assert resolve_export_directory({"export": {"output_dir": str(custom)}}, tmp_path / "Documents") == custom


def test_legacy_exports_migrate_and_repeat_is_idempotent(tmp_path):
    source = tmp_path / "app" / "exports"
    target = tmp_path / "Documents" / "Invoice Hub" / "Exports"
    (source / "claim").mkdir(parents=True)
    (source / "claim" / "manifest.json").write_text("one", encoding="utf-8")
    first = migrate_legacy_exports(source, target)
    second = migrate_legacy_exports(source, target)
    assert first.copied == 1
    assert not first.source_remains
    assert (target / "claim" / "manifest.json").read_text(encoding="utf-8") == "one"
    assert not second.attempted


def test_same_name_conflict_never_overwrites(tmp_path):
    source = tmp_path / "app" / "exports"
    target = tmp_path / "docs"
    source.mkdir(parents=True)
    target.mkdir()
    (source / "report.xlsx").write_bytes(b"legacy")
    (target / "report.xlsx").write_bytes(b"current")
    result = migrate_legacy_exports(source, target)
    assert result.conflicts == 1
    assert (target / "report.xlsx").read_bytes() == b"current"
    assert list(target.glob("report.migrated-*.xlsx"))[0].read_bytes() == b"legacy"


def test_migration_failure_preserves_source(monkeypatch, tmp_path):
    source = tmp_path / "app" / "exports"
    target = tmp_path / "docs"
    source.mkdir(parents=True)
    original = source / "report.xlsx"
    original.write_bytes(b"legacy")

    def fail_copy(*_args, **_kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr("scripts.invoice_fetch.export_paths.shutil.copy2", fail_copy)
    result = migrate_legacy_exports(source, target)
    assert result.failures
    assert result.source_remains
    assert original.read_bytes() == b"legacy"
