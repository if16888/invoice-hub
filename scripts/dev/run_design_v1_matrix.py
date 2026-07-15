"""Run the native Design Baseline screenshot matrix in isolated processes."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "scripts" / "dev" / "capture_design_v1.py"

CASES = [
    (page, state, width, height, scale)
    for page, state in (("overview", "default"), ("imports", "empty"), ("imports", "configured"),
                        ("imports", "missing-authorization"), ("imports", "error"),
                        ("export", "empty"), ("export", "export-blocked"), ("export", "export-ready"),
                        ("settings-mailbox", "default"), ("settings-company", "default"),
                        ("settings-ai", "default"), ("settings-data", "default"), ("settings-about", "default"))
    for width, height, scale in ((1920, 1080, 1.0), (1366, 768, 1.5))
] + [
    ("review", state, width, height, scale)
    for state in ("default", "buyer-mismatch", "buyer-match", "missing-original", "loaded-next-page", "nav-collapsed")
    for width, height in ((1920, 1080), (1440, 900), (1366, 768))
    for scale in (1.0, 1.25, 1.5)
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".codex-artifacts" / "design-v1" / "screenshots")
    parser.add_argument("--geometry", type=Path, default=ROOT / ".codex-artifacts" / "design-v1" / "geometry-report.json")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.geometry.parent.mkdir(parents=True, exist_ok=True)
    args.geometry.write_text(json.dumps({"runs": [], "expected_case_keys": []}, indent=2), encoding="utf-8")
    expected = []
    for page, state, width, height, scale in CASES:
        key = f"{page}:{state}:{width}x{height}@{scale}"
        expected.append(key)
        output = args.output_dir / f"{page}_{width}x{height}_{int(scale * 100)}_{state}.png"
        env = os.environ.copy()
        env["QT_SCALE_FACTOR"] = str(scale)
        env["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
        env.pop("QT_QPA_PLATFORM", None)
        result = subprocess.run([sys.executable, str(CAPTURE), "--width", str(width), "--height", str(height),
                                 "--scale", str(scale), "--page", page, "--state", state,
                                 "--output", str(output), "--geometry-output", str(args.geometry)], env=env, cwd=ROOT)
        if result.returncode or not output.exists() or output.stat().st_size == 0:
            raise SystemExit(f"capture failed: {key}")
    report = json.loads(args.geometry.read_text(encoding="utf-8"))
    actual = [item.get("case_key") for item in report.get("runs", [])]
    if sorted(actual) != sorted(expected) or len(actual) != len(set(actual)):
        raise SystemExit("geometry case set mismatch")
    report["expected_case_keys"] = expected
    args.geometry.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"PASS cases={len(expected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
