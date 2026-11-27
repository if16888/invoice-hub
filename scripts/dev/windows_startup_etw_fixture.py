"""Verify real Windows venv descendant identity without warming a Qt GUI."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from windows_startup_ab import sample_environment
from windows_startup_etw import EtwCapture
from windows_startup_observer import run_observed_checker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--collector", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--mapped-files", action="store_true")
    args = parser.parse_args()
    root = args.output_dir.resolve()
    evidence = root / "evidence"
    evidence.mkdir(parents=True)
    exe = args.fixture.resolve(strict=True)
    if exe.name != "InvoiceHub.exe":
        parser.error("Use the separately built synthetic fixture")
    venv = root / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, timeout=60)
    environment = sample_environment(root / "runtime")
    capture = EtwCapture(args.collector.resolve(strict=True), root / "etw-control", evidence / "fixture.etw.json",
                         mapped_files=args.mapped_files)
    capture.start()
    native = {}
    code = None
    try:
        # Identical venv redirector and subprocess ownership shape to the
        # official checker. The fixture never emits timing/paint evidence.
        code, native = run_observed_checker(
            [venv / "Scripts/python.exe", "-c",
             "import subprocess,sys;sys.exit(subprocess.run([sys.argv[1], sys.argv[2]]).returncode)", exe,
             "--mapped-trace-fixture" if args.mapped_files else "--trace-fixture"],
            cwd=root, env=environment, log=evidence / "fixture.log", exe=exe,
            trace_path=evidence / "fixture.native.json", timeout=20, etw=capture,
        )
    finally:
        trace = capture.finish(native)
    raw_file = evidence / "fixture.etw.json"
    raw = json.loads(raw_file.read_text(encoding="utf-8")) if raw_file.is_file() else {}
    passed = (code == 0 and trace.get("status") in {"complete", "partial"}
              and trace.get("identity_checks", {}).get("depth_matches") is True
              and trace.get("cleanup") is True and trace.get("events_lost") == 0
              and bool(raw.get("raw_scheduler_points")))
    if args.mapped_files:
        passed = (passed and trace.get("mapped_target_marker_published") is True
                  and raw.get("mapped_file_lookup", {}).get("coverage", {}).get("verified") is True)
    report = {"synthetic_non_gui_fixture": True, "fixture_process_exit": code,
              "identity_and_scheduler_verified": passed, "native": native, "etw": trace}
    (evidence / "fixture-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("PERF_AB_ETW_FIXTURE " + json.dumps(report, separators=(",", ":")), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
