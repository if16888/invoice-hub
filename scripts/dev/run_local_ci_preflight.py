"""Run the required CI gates locally before pushing a PR update."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def preflight_commands() -> list[tuple[str, list[str]]]:
    python = sys.executable
    commands = [
        ("CLI help", [python, "-m", "scripts.invoice_fetch", "--help"]),
        ("repository privacy gate", [python, "scripts/check_repo_privacy.py"]),
        ("public export/source tree gate", [python, "scripts/check_public_export.py", "."]),
        ("release metadata gate", [python, "scripts/check_release_metadata.py"]),
        ("architecture policy gate", [python, "scripts/check_architecture_policy.py"]),
        ("Python compile check", [python, "-m", "compileall", "-q", "scripts/invoice_fetch"]),
    ]
    for shard in range(3):
        commands.append(
            (
                f"unit shard {shard}",
                [
                    python,
                    "scripts/dev/run_isolated_unittest.py",
                    "--exclude-dir",
                    "tests/hci_acceptance",
                    "--exclude-module",
                    "tests.test_workbench_native_geometry",
                    "--module-timeout-seconds",
                    "900",
                    "--shard-count",
                    "3",
                    "--shard-index",
                    str(shard),
                ],
            )
        )
    commands.extend(
        [
            ("HCI acceptance", [python, "scripts/dev/run_hci_acceptance.py"]),
            (
                "HCI oracle contract tests",
                [
                    python,
                    "-m",
                    "pytest",
                    "-q",
                    "tests/hci_acceptance/test_mutation_selftest.py",
                    "tests/hci_acceptance/test_report_verdict.py",
                ],
            ),
        ]
    )
    return commands


def main() -> int:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["INVOICE_HUB_TEST_MODE"] = "1"
    if os.name != "nt" and not env.get("QT_QPA_PLATFORM"):
        env["QT_QPA_PLATFORM"] = "offscreen"

    print("LOCAL_CI_PREFLIGHT=RUNNING", flush=True)
    for label, command in preflight_commands():
        print(f"\n=== {label} ===", flush=True)
        result = subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False)
        if result.returncode:
            print(
                f"LOCAL_CI_PREFLIGHT=FAIL gate={label!r} "
                f"exit_code={result.returncode}",
                flush=True,
            )
            return result.returncode if result.returncode > 0 else 1
    print("\nLOCAL_CI_PREFLIGHT=PASS", flush=True)
    print(
        "Native GUI geometry remains a separate Windows-only, non-gating lane; "
        "installer and final UX acceptance remain release gates.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
