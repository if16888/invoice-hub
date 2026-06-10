"""Standalone database backup CLI.

Usage:
    python -m scripts.invoice_fetch.backup_cli
    python -m scripts.invoice_fetch.backup_cli --db runtime/invoices.db --reason before-repair
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import RUNTIME_DIR
from .db_backup import DEFAULT_BACKUP_DIR, create_database_backup, prune_database_backups

DEFAULT_DB_PATH = RUNTIME_DIR / "invoices.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a timestamped backup of the local Invoice Hub SQLite database.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="SQLite database path to back up. Defaults to runtime/invoices.db.",
    )
    parser.add_argument(
        "--backup-dir",
        default=str(DEFAULT_BACKUP_DIR),
        help="Directory where backup files are written. Defaults to runtime/backups.",
    )
    parser.add_argument(
        "--reason",
        default="manual",
        help="Short reason label included in the backup filename.",
    )
    parser.add_argument(
        "--keep-backups",
        type=int,
        default=20,
        help="Keep the newest N .db backups after creating this backup. Default: 20.",
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="Do not remove older backups after creating the new backup.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress normal output; errors are still written to stderr.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.no_prune and args.keep_backups < 1:
        parser.error("--keep-backups must be >= 1 unless --no-prune is set")

    try:
        backup_path = create_database_backup(
            Path(args.db),
            backup_dir=Path(args.backup_dir),
            reason=args.reason,
        )
        removed = []
        if not args.no_prune:
            removed = prune_database_backups(Path(args.backup_dir), keep=args.keep_backups)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Database backup failed: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"Backup created: {backup_path}")
        if removed:
            print(f"Pruned old backups: {len(removed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
