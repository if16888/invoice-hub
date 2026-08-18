"""Run the native splitter interaction contract in fresh processes.

The geometry preflight is authoritative: an unsuitable desktop is reported as
blocked and never converted into a passing native release result.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time


TARGET = (
    "tests.test_workbench_layout."
    "TestWorkbenchShellIntegration."
    "test_user_adjusted_left_splitter_is_not_reset_by_resize"
)


def _run(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode, completed.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=20)
    args = parser.parse_args()
    if args.repeat <= 0:
        parser.error("--repeat must be positive")

    preflight_code, preflight_output = _run(
        [sys.executable, "scripts/dev/check_native_gui_geometry.py"]
    )
    print(preflight_output, end="", flush=True)
    if preflight_code != 0:
        print(
            "NATIVE_SPLITTER_CONTRACT=BLOCKED "
            "because the native geometry preflight was not suitable.",
            flush=True,
        )
        return preflight_code

    passed = 0
    started = time.monotonic()
    command = [sys.executable, "-X", "faulthandler", "-m", "unittest", "-v", TARGET]
    for iteration in range(1, args.repeat + 1):
        print(f"=== native splitter iteration {iteration}/{args.repeat} ===", flush=True)
        code, output = _run(command)
        print(output, end="", flush=True)
        if code == 0:
            passed += 1
            print(f"iteration={iteration} result=PASS exit_code=0", flush=True)
        else:
            print(
                f"iteration={iteration} result=FAIL exit_code={code}; "
                "no retry is performed for this iteration",
                flush=True,
            )
            print(
                f"NATIVE_SPLITTER_CONTRACT=FAIL passed={passed} "
                f"failed={args.repeat - passed}",
                flush=True,
            )
            return code if code > 0 else 1

    elapsed = time.monotonic() - started
    print(
        f"NATIVE_SPLITTER_CONTRACT=PASS passed={passed} failed=0 "
        f"repeat={args.repeat} elapsed_seconds={elapsed:.2f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
