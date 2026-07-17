"""Run native Settings/Preview semantic-state captures in isolated Qt processes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "scripts" / "dev" / "capture_settings_preview_states.py"
STATES = (
    "settings-success",
    "settings-warning",
    "settings-danger",
    "settings-info",
    "preview-normal",
    "preview-hover",
    "preview-focus",
    "preview-disabled",
)
SIZES = ((1920, 1080, 1.0), (1366, 768, 1.5))
CASES = [(state, width, height, scale) for state in STATES for width, height, scale in SIZES]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / ".codex-artifacts" / "design-v1" / "settings-preview-screenshots",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / ".codex-artifacts" / "design-v1" / "settings-preview-report.json",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps({"runs": [], "expected_case_keys": []}, indent=2),
        encoding="utf-8",
    )

    expected: list[str] = []
    for state, width, height, scale in CASES:
        key = f"{state}:{width}x{height}@{scale}"
        expected.append(key)
        output = args.output_dir / f"{state}_{width}x{height}_{int(scale * 100)}.png"
        env = os.environ.copy()
        env["QT_SCALE_FACTOR"] = str(scale)
        env["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
        env.pop("QT_QPA_PLATFORM", None)
        result = subprocess.run(
            [
                sys.executable,
                str(CAPTURE),
                "--width",
                str(width),
                "--height",
                str(height),
                "--scale",
                str(scale),
                "--state",
                state,
                "--output",
                str(output),
                "--report",
                str(args.report),
            ],
            env=env,
            cwd=ROOT,
        )
        if result.returncode or not output.exists() or output.stat().st_size == 0:
            raise SystemExit(f"settings/preview capture failed: {key}")

    report = json.loads(args.report.read_text(encoding="utf-8"))
    actual = [run.get("case_key") for run in report.get("runs", [])]
    if sorted(actual) != sorted(expected) or len(actual) != len(set(actual)):
        raise SystemExit("settings/preview case set mismatch")
    if any(run.get("result") != "PASS" for run in report.get("runs", [])):
        raise SystemExit("settings/preview report contains failures")

    report["expected_case_keys"] = expected
    args.report.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"PASS settings_preview_cases={len(expected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
