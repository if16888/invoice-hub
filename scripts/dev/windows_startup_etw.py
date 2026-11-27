"""Own one short, target-scoped real-time ETW capture alongside the checker."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import uuid


def publish(path: Path, content: str) -> None:
    pending = path.with_suffix(path.suffix + ".new")
    pending.write_text(content, encoding="utf-8")
    pending.replace(path)


class EtwCapture:
    def __init__(self, dll: Path, directory: Path, evidence: Path):
        self.dll = dll
        self.directory = directory
        self.evidence = evidence
        self.name = f"InvoiceHubStartup-{uuid.uuid4().hex}"
        self.process = None
        self.ready = False
        self.error = None

    def start(self) -> None:
        """Start the consumer before launching the unchanged checker."""
        try:
            self.directory.mkdir()
            self.process = subprocess.Popen(
                ["dotnet", str(self.dll), self.name, str(self.directory)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            marker = self.directory / "ready.json"
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if marker.is_file():
                    status = json.loads(marker.read_text(encoding="utf-8"))
                    self.ready = status.get("status") == "ready" and status.get("session") == self.name
                    if not self.ready:
                        self.error = status.get("error") or "Collector did not open the requested session"
                    return
                if self.process.poll() is not None:
                    break
                time.sleep(0.03)
            self.error = "Collector readiness not observed"
        except Exception as exc:
            self.error = f"Collector start: {type(exc).__name__}"

    def checker_started(self, pid: int) -> None:
        if self.ready:
            try:
                publish(self.directory / "checker.pid", str(pid))
            except OSError as exc:
                self.error = f"Checker identity marker: {type(exc).__name__}"

    def finish(self, native: dict) -> dict:
        """Always produce an explicit ETW result. Never rerun the checker."""
        report = {"status": "unavailable", "error": self.error}
        result = self.directory / "result.json"
        try:
            if self.process is None:
                return report
            marker = {
                "gui_pid": native.get("gui_pid"),
                "gui_creation_unix_ms": native.get("gui_creation_unix_ms"),
                "checker_lineage_depth": native.get("checker_lineage_depth"),
                "ui_threads": native.get("ui_threads", []),
                "markers": {
                    name: {"qpc_ms": values.get("qpc_ms")}
                    for name, values in native.get("events", {}).items()
                    if name in {
                        "splash-like_seen", "splash-like_visible",
                        "main-like_visible", "valid_probe_file_observed",
                    }
                },
            }
            publish(self.directory / "stop.json", json.dumps(marker))
            try:
                self.process.wait(timeout=24)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
                self.error = "Collector timed out after the checker returned"
            if result.is_file():
                full = json.loads(result.read_text(encoding="utf-8"))
                shutil.copyfile(result, self.evidence)
                report = {"artifact": self.evidence.name, **compact(full)}
                if self.error:
                    report.update(status="unavailable", bridge_error=self.error)
                elif full.get("status") in {"complete", "partial"}:
                    report["raw_log_transport"] = print_raw_chunks(self.evidence)
            else:
                report["error"] = self.error or "Collector did not return evidence"
        except Exception as exc:
            report = {"status": "unavailable", "error": self.error or f"Collector finish: {type(exc).__name__}"}
        finally:
            # Emergency cleanup is limited to the one unique name the child
            # explicitly claimed. Never stop another recorder/NT Kernel Logger.
            claim = self.directory / "claimed.json"
            try:
                if self.process is not None and self.process.poll() is None:
                    self.process.kill()
                    self.process.wait(timeout=5)
                if claim.is_file() and json.loads(claim.read_text(encoding="utf-8")).get("session") == self.name:
                    already_clean = result.is_file() and json.loads(result.read_text(encoding="utf-8")).get("cleanup") is True
                    if not already_clean:
                        cleanup = subprocess.run(["logman.exe", "stop", self.name, "-ets"],
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                 timeout=12, check=False).returncode == 0
                        report["fallback_cleanup_succeeded"] = cleanup
                        print(f"PERF_AB_ETW_CLEANUP owned_session={self.name} stop_succeeded={cleanup}", flush=True)
            except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
                report["fallback_cleanup_error"] = type(exc).__name__
                print(f"PERF_AB_ETW_CLEANUP owned_session={self.name} error={type(exc).__name__}", flush=True)
        return report


def compact(full: dict) -> dict:
    """Keep enough target-only evidence in CI logs without dumping all events."""
    omitted = {"raw_scheduler_points", "raw_thread_lifetimes", "raw_hard_faults", "threads"}
    summary = {key: value for key, value in full.items() if key not in omitted}
    summary["raw_scheduler_point_count"] = len(full.get("raw_scheduler_points", []))
    threads = full.get("threads", [])
    summary["target_thread_count"] = len(threads)
    summary["ui_threads"] = []
    for thread in threads:
        if not thread.get("ui_thread"):
            continue
        item = dict(thread)
        for key, limit in (("longest_off_cpu", 8), ("longest_hard_faults", 3)):
            item[key] = [
                {**event, "module_stacks": [stack[:24] for stack in event.get("module_stacks", [])[:2]]}
                for event in thread[key][:limit]
            ]
        summary["ui_threads"].append(item)
    summary["log_stack_frame_limit"] = 24
    # Target worker waits can identify another app thread doing the work;
    # keep counts for all threads and their detailed data in the artifact.
    summary["other_thread_hard_fault_count"] = sum(
        t["hard_fault_count"] for t in threads if not t.get("ui_thread")
    )
    return summary


def print_raw_chunks(path: Path) -> dict:
    """Retain small verified-target evidence in the downloadable job log too."""
    raw = path.read_bytes()
    packed = gzip.compress(raw, mtime=0)
    digest = hashlib.sha256(raw).hexdigest()
    if len(packed) > 512 * 1024:
        return {"included": False, "compressed_bytes": len(packed), "sha256": digest}
    encoded = base64.b64encode(packed).decode("ascii")
    chunks = [encoded[i:i + 10000] for i in range(0, len(encoded), 10000)]
    for index, chunk in enumerate(chunks, 1):
        print("PERF_AB_ETW_RAW " + json.dumps({
            "name": path.name, "part": index, "parts": len(chunks), "sha256": digest,
            "codec": "gzip+base64", "data": chunk,
        }, separators=(",", ":")), flush=True)
    return {"included": True, "compressed_bytes": len(packed), "sha256": digest}
