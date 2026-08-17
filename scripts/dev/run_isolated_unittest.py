"""Run every unittest module in a fresh Python process.

This is intentionally fail-fast and does not retry a failed module.  Running
modules in separate processes preserves the complete discovered test set while
preventing Qt/PySide object graphs from accumulating across unrelated modules.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path


_RAN_RE = re.compile(r"Ran (\d+) tests? in ")
_SKIPPED_RE = re.compile(r"skipped=(\d+)")
_MODULE_SKIP_RE = re.compile(r"unittest\.case\.SkipTest:\s*(.+)")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _module_names(root: Path, pattern: str) -> list[str]:
    modules = []
    for path in sorted(root.rglob(pattern)):
        if not path.is_file() or path.name == "__init__.py":
            continue
        relative = path.relative_to(root.parent).with_suffix("")
        modules.append(".".join(relative.parts))
    return modules


def _exit_hex(code: int) -> str:
    return f"0x{code & 0xFFFFFFFF:08X}"


def _run_module(module: str, timeout_seconds: int) -> tuple[int, str, int, int]:
    command = [sys.executable, "-X", "faulthandler", "-m", "unittest", "-v", module]
    print(f"\n=== isolated unittest module: {module} ===", flush=True)
    print("command:", " ".join(command), flush=True)
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        output, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()
        elapsed_ms = int((time.monotonic() - started) * 1000)
        print(output, end="", flush=True)
        print(
            f"MODULE TIMEOUT: {module} after {elapsed_ms} ms; "
            "child process was terminated; no retry is performed.",
            flush=True,
        )
        return 124, output, 0, 0

    elapsed_ms = int((time.monotonic() - started) * 1000)
    print(output, end="", flush=True)
    ran_match = _RAN_RE.search(output)
    skipped_match = _SKIPPED_RE.search(output)
    ran = int(ran_match.group(1)) if ran_match else 0
    skipped = int(skipped_match.group(1)) if skipped_match else 0
    print(
        f"module_exit={process.returncode} ({_exit_hex(process.returncode)}) "
        f"elapsed_ms={elapsed_ms} tests={ran} skipped={skipped}",
        flush=True,
    )
    if process.returncode != 0:
        module_skip = _MODULE_SKIP_RE.search(output)
        if module_skip:
            print(f"module_skip=1 reason={module_skip.group(1).strip()}", flush=True)
            return 0, output, ran, max(skipped, 1)
    return process.returncode, output, ran, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests-dir", type=Path, default=Path("tests"))
    parser.add_argument("--pattern", default="test_*.py")
    parser.add_argument("--module-timeout-seconds", type=int, default=900)
    args = parser.parse_args()

    tests_dir = args.tests_dir.resolve()
    if not tests_dir.is_dir():
        parser.error(f"tests directory does not exist: {tests_dir}")
    if args.module_timeout_seconds <= 0:
        parser.error("--module-timeout-seconds must be positive")

    modules = _module_names(tests_dir, args.pattern)
    if not modules:
        parser.error(f"no test modules matched {args.pattern!r} under {tests_dir}")

    print(f"isolated_modules={len(modules)}", flush=True)
    total_tests = 0
    total_skipped = 0
    for module in modules:
        returncode, _output, ran, skipped = _run_module(
            module, args.module_timeout_seconds
        )
        total_tests += ran
        total_skipped += skipped
        if returncode != 0:
            print(
                f"ISOLATED TEST FAILURE: {module} exited {returncode} "
                f"({_exit_hex(returncode)}); no retry is performed.",
                flush=True,
            )
            return returncode if returncode > 0 else 1

    print(
        f"ISOLATED TEST SUITE PASS: modules={len(modules)} "
        f"tests={total_tests} skipped={total_skipped}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
