"""Platform-independent checks for the diagnostic harness, not a Windows gate."""

import argparse
from contextlib import contextmanager
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.dev import windows_startup_ab as ab


class StartupABDiagnosticTests(unittest.TestCase):
    def test_default_order_is_balanced_and_rejects_arbitrary_sequences(self):
        for given in ("ABBA,BAAB", "BAAB,ABBA", "ABBA", "BAAB"):
            order = ab.sample_order(given)
            self.assertEqual(order.count("A"), order.count("B"))
        for invalid in ("", "AAAA", "ABBA,ABBA", "ABBABAAB"):
            with self.assertRaises(argparse.ArgumentTypeError):
                ab.sample_order(invalid)

    def test_measure_uses_original_checker_truth_and_retains_failed_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, evidence = root / "work", root / "evidence"
            work.mkdir()
            evidence.mkdir()
            build = ab.Build("A", ab.CANDIDATE, root / "InvoiceHub.exe", "synthetic-hash",
                             ab.REPO / "scripts/check_startup_time.py", Path(sys.executable))
            totals = iter((6546, 1326))

            def fake_checker(_cmd, *, cwd, env, log, **_kwargs):
                total = next(totals)
                runtime = Path(env["INVOICE_HUB_RUNTIME_DIR"])
                self.assertEqual(runtime, cwd / "runtime")
                self.assertIn("legacy_qsettings_v1=true", (runtime / "workbench.ini").read_text())
                metrics = {"PROBE_CONTRACT": "main_window_first_paint_v1", "QT_PAINT_EVENT_COMPLETED": True,
                           "PROCESS_RETURN_CODE": 0, "APP_INIT_MS": 126, "TOTAL_STARTUP_MS": total,
                           "STARTUP_MS": total, "MAIN_WINDOW_SHOW_MS": 900, "FIRST_PAINT_MS": total - 126,
                           "LAUNCH_STAGE_MS": {"splash_constructed": 30, "splash_shown": 480}}
                raw = cwd / "bench-local/results/startup_metrics_0.json"
                raw.parent.mkdir(parents=True)
                ab.write_json(raw, metrics)
                log.write_text("synthetic checker result", encoding="utf-8")
                return int(total > ab.THRESHOLDS["installed"])

            with patch.object(ab, "run_logged", side_effect=fake_checker):
                failed = ab.collect_sample(build, "installed", 1, work, evidence, fresh_install=False)
                passed = ab.collect_sample(build, "installed", 2, work, evidence, fresh_install=False)
            self.assertFalse(failed["gate_pass"])
            self.assertTrue(passed["gate_pass"])
            self.assertEqual(failed["truth_errors"], [])
            self.assertEqual(failed["metrics"]["TOTAL_STARTUP_MS"], 6546)
            self.assertIsNone(passed["source_sha"])
            self.assertEqual(passed["claimed_source_sha"], ab.CANDIDATE)
            rows = [json.loads(line) for line in (evidence / "samples.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(len(list(evidence.glob("*.metrics.json"))), 2)
            summary = ab.summarize(rows, 2)
            self.assertFalse(summary["all_gates_passed"])
            self.assertEqual(summary["groups"]["installed-A"]["gate_passes"], 1)
            self.assertFalse(ab.summarize([passed], 2)["all_gates_passed"])

    def test_existing_inno_registration_blocks_before_install(self):
        build = ab.Build("A", ab.CANDIDATE, Path("unused"), "hash", Path("unused"), Path(sys.executable))
        with patch.object(ab, "installer_registrations", return_value=[("existing", "0.1.8")]), \
                patch.object(ab, "run_logged") as command:
            with self.assertRaisesRegex(ab.DiagnosticError, "Existing Invoice Hub"):
                with ab.installed_executable(build, Path("unused"), {}):
                    self.fail("Should not enter installation")
            command.assert_not_called()

    def test_install_failure_preserves_bounded_inno_log_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            evidence.mkdir()
            build = ab.Build("A", ab.CANDIDATE, root / "InvoiceHub.exe", "hash", Path("unused"), Path(sys.executable))

            @contextmanager
            def failed_install(_build, sample_root, _record):
                (sample_root / "setup-inno.log").write_text("old\n" * 10_000 + "FINAL ERROR", encoding="utf-8")
                raise ab.DiagnosticError("Synthetic setup failure")
                yield  # pragma: no cover

            with patch.object(ab, "installed_executable", failed_install):
                record = ab.collect_sample(build, "installed", 1, root / "work", evidence, fresh_install=True)
            self.assertFalse(record["gate_pass"])
            self.assertIn("Synthetic setup failure", record["error"])
            tail = (evidence / "installed-01-A.install-failure.log").read_text(encoding="utf-8")
            self.assertIn("FINAL ERROR", tail)
            self.assertLess(len(tail), 12_100)

    def test_install_verifies_embedded_version_and_cleans_owned_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / "InvoiceHub.exe"
            exe.write_bytes(b"synthetic exact build")
            build = ab.Build("A", ab.CANDIDATE, exe, ab.sha256(exe), Path("unused"), Path(sys.executable),
                             version="0.2.0", setup=root / "setup.exe", setup_hash="setup-hash")
            sample = root / "sample"
            sample.mkdir()
            install = sample / "install"
            registrations = []
            calls = []

            def fake_command(cmd, *, stage, **_kwargs):
                calls.append(stage)
                if stage.endswith("/install"):
                    install.mkdir()
                    (install / "InvoiceHub.exe").write_bytes(exe.read_bytes())
                    (install / "unins000.exe").write_bytes(b"synthetic uninstaller")
                    registrations.append((str(install), build.version))
                elif stage.endswith("/version-probe"):
                    self.assertEqual(cmd[1], "--version-probe-file")
                    ab.write_json(Path(cmd[2]), {"contract": "invoice_hub_build_version_v1", "app_version": "v0.2.0"})
                elif stage.endswith("/uninstall"):
                    self.assertEqual(Path(cmd[0]), install / "unins000.exe")
                    for path in install.iterdir():
                        path.unlink()
                    install.rmdir()
                    registrations.clear()
                return 0

            record = {"sample": "installed-01-A"}
            with patch.object(ab, "installer_registrations", side_effect=lambda: list(registrations)), \
                    patch.object(ab, "run_logged", side_effect=fake_command):
                with ab.installed_executable(build, sample, record) as installed:
                    self.assertEqual(installed, install / "InvoiceHub.exe")
                    self.assertTrue(record["install_verified"])
                    self.assertEqual(record["installed_exe_sha256"], build.exe_hash)
                self.assertTrue(record["uninstall_verified"])
            self.assertEqual(calls, ["installed-01-A/install", "installed-01-A/version-probe", "installed-01-A/uninstall"])


if __name__ == "__main__":
    unittest.main()
