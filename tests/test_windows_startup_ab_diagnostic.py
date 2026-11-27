"""Platform-independent checks for the diagnostic harness, not a Windows gate."""

import argparse
import base64
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
import gzip
import hashlib
import json
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.dev import windows_startup_ab as ab
from scripts.dev import windows_startup_observer as observer
from scripts.dev import windows_startup_etw as etw


class StartupABDiagnosticTests(unittest.TestCase):
    def test_descendant_depth_accepts_windows_python_redirector_only_with_root_chain(self):
        entries = [
            {"pid": 10, "parent": 1}, {"pid": 11, "parent": 10},
            {"pid": 12, "parent": 11}, {"pid": 99, "parent": 1},
            {"pid": 22, "parent": 23}, {"pid": 23, "parent": 22},
        ]
        self.assertEqual(observer.descendant_depth(entries, 10, 12), 2)
        self.assertEqual(observer.descendant_depth(entries, 10, 11), 1)
        self.assertIsNone(observer.descendant_depth(entries, 10, 99))
        self.assertIsNone(observer.descendant_depth(entries, 10, 22))

    def test_raw_etw_log_chunks_round_trip_exact_target_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.etw.json"
            original = json.dumps({"raw_scheduler_points": [[42, n, "out"] for n in range(4000)]}).encode()
            target.write_bytes(original)
            with patch("sys.stdout", new_callable=StringIO) as stream:
                summary = etw.print_raw_chunks(target)
            rows = [json.loads(line.removeprefix("PERF_AB_ETW_RAW ")) for line in stream.getvalue().splitlines()]
            packed = base64.b64decode("".join(row["data"] for row in rows))
            self.assertEqual(gzip.decompress(packed), original)
            self.assertEqual(summary["sha256"], hashlib.sha256(original).hexdigest())
            self.assertTrue(summary["included"])
            self.assertEqual([r["part"] for r in rows], list(range(1, len(rows) + 1)))

    def test_focused_etw_plan_does_not_rebuild_a_or_installers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collector = root / "StartupEtw.dll"
            collector.touch()
            optimized = "8" * 40
            calls = []
            raw_points = 1

            def build(label, revision, *_args):
                return ab.Build(label, revision, root / "InvoiceHub.exe", "synthetic",
                                root / "checker.py", Path(sys.executable), source=root)

            def sample(obj, mode, ordinal, *_args, **kwargs):
                calls.append((obj.label, mode, ordinal, kwargs))
                return {"mode": mode, "index": ordinal, "label": obj.label, "gate_pass": True, "metrics": None,
                        "fresh_inno_install": False, "etw_requested": True,
                        "etw": {"status": "partial", "raw_scheduler_point_count": raw_points}}

            fake_os = SimpleNamespace(name="nt", environ=os.environ, cpu_count=os.cpu_count)
            fake_sys = SimpleNamespace(version_info=(3, 11, 0), maxsize=sys.maxsize,
                                       version="3.11 (simulated)", executable=sys.executable, stderr=sys.stderr)
            with patch.object(ab, "os", fake_os), patch.object(ab, "sys", fake_sys), \
                    patch.object(ab.platform, "machine", return_value="AMD64"), \
                    patch.object(ab, "build_source", side_effect=build) as builder, \
                    patch.object(ab, "collect_sample", side_effect=sample), \
                    patch.object(ab, "record_system_state"), patch.object(ab, "build_installer") as installer:
                code = ab.main(["--output-dir", str(root / "out"), "--optimized-sha", optimized,
                                "--etw-collector", str(collector), "--etw-focus"])
                raw_points = 0
                missing_evidence_code = ab.main(["--output-dir", str(root / "no-points"), "--optimized-sha", optimized,
                                                 "--etw-collector", str(collector), "--etw-focus"])
            self.assertEqual(code, 0)
            self.assertEqual(missing_evidence_code, 1)
            self.assertEqual([c.args[:2] for c in builder.call_args_list], [("F", optimized), ("B", ab.BASELINE)] * 2)
            self.assertEqual("".join(c[0] for c in calls), "FFBBFFBB")
            self.assertTrue(all(c[1] == "portable" and c[3]["observe_native"] for c in calls))
            installer.assert_not_called()

    def test_mapped_file_focus_builds_only_f_and_observes_two_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collector = root / "StartupEtw.dll"
            collector.touch()
            optimized = "8cfe7b9f5b630323d7e46a8134432165c6741010"
            calls = []

            def build(label, revision, *_):
                return ab.Build(label, revision, root / "InvoiceHub.exe", "synthetic", root / "checker.py",
                                Path(sys.executable), source=root)

            def sample(obj, mode, ordinal, _work, _evidence, **kwargs):
                calls.append((obj.label, mode, ordinal, kwargs))
                return {"mode": mode, "label": obj.label, "index": ordinal, "gate_pass": True,
                        "metrics": None, "fresh_inno_install": False, "etw_requested": True,
                        "etw": {"status": "partial", "raw_scheduler_point_count": 1}}

            fake_os = SimpleNamespace(name="nt", environ=os.environ, cpu_count=os.cpu_count)
            fake_sys = SimpleNamespace(version_info=(3, 11, 0), maxsize=sys.maxsize,
                                       version="3.11 (simulated)", executable=sys.executable, stderr=sys.stderr)
            with patch.object(ab, "os", fake_os), patch.object(ab, "sys", fake_sys), \
                    patch.object(ab.platform, "machine", return_value="AMD64"), \
                    patch.object(ab, "build_source", side_effect=build) as builder, \
                    patch.object(ab, "collect_sample", side_effect=sample), \
                    patch.object(ab, "record_system_state"), patch.object(ab, "build_installer") as installer:
                code = ab.main(["--output-dir", str(root / "out"), "--optimized-sha", optimized,
                                "--etw-collector", str(collector), "--mapped-file-focus"])
            self.assertEqual(code, 0)
            self.assertEqual([call.args[:2] for call in builder.call_args_list], [("F", optimized)])
            self.assertEqual([c[:3] for c in calls], [("F", "portable", 1), ("F", "portable", 2)])
            self.assertTrue(all(c[3]["mapped_files"] and c[3]["observe_native"] for c in calls))
            installer.assert_not_called()

    def test_live_mapping_marker_stays_private_and_is_not_used_by_old_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private = root / "control"
            private.mkdir()
            evidence = root / "evidence.json"
            exe = root / "InvoiceHub.exe"
            capture = etw.EtwCapture(root / "collector.dll", private, evidence, mapped_files=True)
            capture.ready = True
            capture.target_verified(42, 11, exe, 116444736000000111, 2)
            marker = json.loads((private / "target.json").read_text())
            self.assertEqual(marker, {"pid": 42, "checker_pid": 11, "exe_path": str(exe.resolve()),
                                      "creation_filetime": 116444736000000111, "checker_lineage_depth": 2})
            capture.target_verified(43, 11, exe, 1, 1)
            self.assertEqual(json.loads((private / "target.json").read_text()), marker)
            self.assertFalse(evidence.exists())
            legacy = root / "legacy"
            legacy.mkdir()
            old = etw.EtwCapture(root / "collector.dll", legacy, evidence)
            old.ready = True
            old.target_verified(42, 11, exe, 1, 2)
            self.assertFalse((legacy / "target.json").exists())
            compact = etw.compact({"raw_mapped_faults": [1, 2], "mapped_file_lookup": {"observed_queries": 1}})
            self.assertNotIn("raw_mapped_faults", compact)
            self.assertEqual(compact["raw_mapped_fault_count"], 2)

    def test_mapping_birth_marker_requires_live_handle(self):
        api = observer.WindowsApi.__new__(observer.WindowsApi)
        def times(_handle, creation, *_):
            creation._obj.dwHighDateTime = 1
            creation._obj.dwLowDateTime = 2
            return True
        api.process_times = times
        api.wait = lambda *_: 258
        self.assertEqual(api.live_creation_filetime(99), (1 << 32) | 2)
        api.wait = lambda *_: 0
        self.assertIsNone(api.live_creation_filetime(99))

    def test_three_revision_plan_retains_cold_trace_warm_control_and_two_real_installs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collector = root / "StartupEtw.dll"
            collector.touch()
            optimized = "7" * 40
            calls = []

            def build(label, revision, *_args):
                return ab.Build(label, revision, root / "InvoiceHub.exe", "synthetic",
                                root / "checker.py", Path(sys.executable), source=root)

            def sample(obj, mode, ordinal, _work, _evidence, **kwargs):
                calls.append((obj.label, mode, ordinal, kwargs))
                return {"mode": mode, "index": ordinal, "label": obj.label, "gate_pass": True,
                        "metrics": None, "fresh_inno_install": kwargs["fresh_install"],
                        "etw_requested": "etw_collector" in kwargs,
                        "etw": {"status": "partial", "raw_scheduler_point_count": 1} if "etw_collector" in kwargs else {}}

            fake_os = SimpleNamespace(name="nt", environ=os.environ, cpu_count=os.cpu_count)
            fake_sys = SimpleNamespace(version_info=(3, 11, 0), maxsize=sys.maxsize,
                                       version="3.11 (simulated)", executable=sys.executable, stderr=sys.stderr)
            with patch.object(ab, "os", fake_os), patch.object(ab, "sys", fake_sys), \
                    patch.object(ab.platform, "machine", return_value="AMD64"), \
                    patch.object(ab, "build_source", side_effect=build) as builder, \
                    patch.object(ab, "collect_sample", side_effect=sample), \
                    patch.object(ab, "record_system_state") as state, \
                    patch.object(ab, "require_no_installation"), \
                    patch.object(ab, "find_iscc", return_value=root / "ISCC.exe"), \
                    patch.object(ab, "record_iscc"), patch.object(ab, "build_installer") as installer:
                code = ab.main(["--output-dir", str(root / "output"), "--mode", "both",
                                "--disposable-runner", "--optimized-sha", optimized, "--etw-collector", str(collector)])
            self.assertEqual(code, 0)
            self.assertEqual([call.args[:2] for call in builder.call_args_list],
                             [("F", optimized), ("A", ab.CANDIDATE), ("B", ab.BASELINE)])
            self.assertEqual("".join(c[0] for c in calls), "FFABBAFBAFFABFF")
            self.assertEqual([c[3]["observe_native"] for c in calls], [True] * 7 + [False] * 6 + [True, False])
            self.assertEqual([c[1] for c in calls], ["portable"] * 13 + ["installed"] * 2)
            self.assertEqual([c.args[1] for c in state.call_args_list], ["before-first", "after-first"])
            installer.assert_called_once()
            self.assertEqual(installer.call_args.args[0].label, "F")
            self.assertEqual(ab.THRESHOLDS, {"portable": 5000, "installed": 2000})

    def test_probe_observer_shares_deletion_and_closes_owned_read_handle(self):
        api = observer.WindowsApi.__new__(observer.WindowsApi)
        calls = []
        api.create_file = lambda *args: calls.append(args) or 42
        api.read_file = lambda *_args: False
        api.close = lambda handle: calls.append(handle)
        self.assertEqual(api.read_probe(Path("synthetic-probe.json")), b"")
        self.assertEqual(calls[0][1:3], (0x80000000, 7))
        self.assertEqual(calls[1], 42)

    def test_etw_summary_retains_ui_waits_without_raw_series_in_console(self):
        report = etw.compact({
            "status": "partial", "raw_scheduler_points": [1, 2],
            "threads": [
                {"thread_id": 42, "ui_thread": True, "hard_fault_count": 3,
                 "longest_off_cpu": [{"module_stacks": [["Qt6Gui.dll+0x1"] * 64]}],
                 "longest_hard_faults": []},
                {"thread_id": 43, "ui_thread": False, "hard_fault_count": 5},
            ],
        })
        self.assertNotIn("raw_scheduler_points", report)
        self.assertEqual(report["raw_scheduler_point_count"], 2)
        self.assertEqual(report["other_thread_hard_fault_count"], 5)
        self.assertEqual(len(report["ui_threads"][0]["longest_off_cpu"][0]["module_stacks"][0]), 24)

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

    def test_native_liveness_uses_wait_not_undefined_active_exit_filetime(self):
        api = observer.WindowsApi.__new__(observer.WindowsApi)
        api.process_io = lambda *_: False
        api.process_memory = lambda *_: False

        def process_times(_handle, _creation, exit_time, _kernel, _user):
            exit_time._obj.dwLowDateTime = 123456  # arbitrary undefined live-process exit bytes
            return True

        api.process_times = process_times
        for status, expected in ((0, True), (258, False), (0xFFFFFFFF, None)):
            with self.subTest(status=status):
                api.wait = lambda _handle, _timeout: status
                result = api.counters(100)
                self.assertIs(result["exited"], expected)
                self.assertEqual(result["wait_status"], status)

    def test_observer_failure_keeps_single_official_checker_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "launches.txt"
            script = "from pathlib import Path; import sys; p=Path(sys.argv[1]); p.open('a').write('one launch'); sys.exit(1)"
            with patch.object(observer, "WindowsApi", side_effect=OSError("Synthetic unavailable counters")):
                code, summary = observer.run_observed_checker([sys.executable, "-c", script, marker], cwd=root,
                    env=ab.child_environment(), log=root / "checker.log", exe=root / "InvoiceHub.exe",
                    trace_path=root / "trace.json", timeout=5)
            self.assertEqual(code, 1)
            self.assertEqual(marker.read_text(), "one launch")
            self.assertIn("Synthetic unavailable counters", summary["observer_error"])
            self.assertEqual(summary["sample_count"], 0)
            self.assertEqual(json.loads((root / "trace.json").read_text())["checker_exit"], 1)

    def test_observer_records_window_events_and_scoped_counter_summary(self):
        class FakeApi:
            def __init__(self):
                self.polls = 0

            def processes(self):
                self.polls += 1
                return [{"pid": 42, "threads": 3}]

            def open_exact_child(self, *_args):
                return 42, 100

            def counters(self, _handle):
                return {"exited": False, "kernel_cpu_ms": self.polls, "user_cpu_ms": self.polls * 2,
                        "read_ops": self.polls, "read_bytes": self.polls * 10, "page_faults": self.polls * 3}

            def windows(self, _pid):
                return [{"role": "splash-like" if self.polls < 3 else "main-like", "visible": True}]

            def modules(self, _pid):
                return {"module_count": 3, "notable_basenames": ["Qt6Gui.dll"]}

            def close(self, _handle):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(observer, "WindowsApi", FakeApi), patch.object(observer, "POLL_SECONDS", 0.01):
                code, summary = observer.run_observed_checker([sys.executable, "-c", "import time; time.sleep(.17)"],
                    cwd=root, env=ab.child_environment(), log=root / "checker.log", exe=root / "InvoiceHub.exe",
                    trace_path=root / "trace.json", timeout=5)
            self.assertEqual(code, 0)
            self.assertEqual(summary["gui_pid"], 42)
            self.assertIn("splash-like_visible", summary["events"])
            self.assertIn("main-like_visible", summary["events"])
            self.assertIn("read_bytes", summary["events"]["main-like_visible"])
            self.assertIn("main-like_visible", summary["module_snapshots"])
            self.assertTrue(summary["second_marks"])
            self.assertEqual(summary["available_samples"]["page_faults"], summary["sample_count"])

    def test_baseline_first_plan_builds_only_b_and_observes_both_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            calls = []
            build = ab.Build("B", ab.BASELINE, Path("unused"), "hash", Path("unused"), Path(sys.executable))

            def collect(obj, mode, ordinal, _work, _evidence, **kwargs):
                calls.append((obj.label, mode, ordinal, kwargs))
                return {"mode": mode, "label": obj.label, "gate_pass": False, "metrics": None,
                        "fresh_inno_install": False}

            # Mock the Windows/Python 3.11 gate and expensive boundary operations;
            # pathlib still uses the real local filesystem. No Windows claim.
            fake_os = SimpleNamespace(name="nt", environ=os.environ, cpu_count=os.cpu_count)
            fake_sys = SimpleNamespace(version_info=(3, 11, 0), maxsize=sys.maxsize,
                                       version="3.11 (simulated)", executable=sys.executable, stderr=sys.stderr)
            with patch.object(ab, "os", fake_os), patch.object(ab, "sys", fake_sys), \
                    patch.object(ab.platform, "machine", return_value="AMD64"), \
                    patch.object(ab, "build_source", return_value=build) as build_source, \
                    patch.object(ab, "collect_sample", side_effect=collect), \
                    patch.object(ab, "record_system_state") as state, \
                    patch.object(ab, "build_installer") as installer, \
                    patch.object(ab, "native_qt_samples", return_value=True) as native:
                code = ab.main(["--output-dir", str(output), "--baseline-first", "--native-qt"])
            self.assertEqual(code, 1)  # simulated gate misses remain failures
            build_source.assert_called_once()
            self.assertEqual(build_source.call_args.args[:2], ("B", ab.BASELINE))
            self.assertEqual(calls, [("B", "portable", 1, {"fresh_install": False, "observe_native": True}),
                                     ("B", "portable", 2, {"fresh_install": False, "observe_native": True})])
            self.assertEqual([call.args[1] for call in state.call_args_list], ["before-first", "after-first"])
            installer.assert_not_called()
            native.assert_called_once()
            self.assertEqual(set(native.call_args.args[0]), {"B"})


if __name__ == "__main__":
    unittest.main()
