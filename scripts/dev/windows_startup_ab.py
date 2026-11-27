"""Native Windows A/B startup diagnostics for two exact Invoice Hub sources.

This builds in a new local directory, never publishes artifacts, and uses the
release startup checker unchanged. See docs/windows-startup-ab.md.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time
import zipfile


REPO = Path(__file__).resolve().parents[2]
CANDIDATE = "ca358f9f62e4d8912a72f64f4600de52d9746acb"
BASELINE = "b30a42eef585624a7d30cb792dce46f5f0548262"
LOCKS = ("requirements.lock.txt", "requirements-desktop.lock.txt", "requirements-build.lock.txt")
THRESHOLDS = {"portable": 5000, "installed": 2000}
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{B4A5B8B8-0F83-4E8B-9A8D-3C4321609C5D}_is1"


class DiagnosticError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sample_order(value: str) -> str:
    blocks = value.upper().split(",")
    if not 1 <= len(blocks) <= 2 or any(b not in {"ABBA", "BAAB"} for b in blocks) or len(set(blocks)) != len(blocks):
        raise argparse.ArgumentTypeError("use ABBA, BAAB, ABBA,BAAB or BAAB,ABBA")
    return "".join(blocks)


def child_environment() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("INVOICE_HUB_BUILD_VERSION", "INVOICE_HUB_STARTUP_PROBE", "INVOICE_HUB_STARTUP_PROBE_FILE",
                "INVOICE_HUB_TEST_MODE", "PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE",
                "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_PLATFORMTHEME", "QT_STYLE_OVERRIDE"):
        env.pop(key, None)
    env.update(QT_QPA_PLATFORM="windows", PYTHONIOENCODING="utf-8",
               PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring")
    return env


def sample_environment(runtime: Path) -> dict[str, str]:
    runtime.mkdir(parents=True)
    # Both exact releases recognize this marker. Do not read legacy HKCU
    # workbench sizes or a user's config, credentials, database, or invoices.
    (runtime / "workbench.ini").write_text("[migration]\nlegacy_qsettings_v1=true\n", encoding="utf-8")
    env = child_environment()
    env["INVOICE_HUB_RUNTIME_DIR"] = str(runtime)
    temporary = runtime.parent / "tmp"
    temporary.mkdir()
    env.update(TMP=str(temporary), TEMP=str(temporary))
    return env


def run_logged(cmd, *, cwd: Path, env: dict, log: Path, timeout: int, stage: str, check=True) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    print(f"PERF_AB_STEP {stage} started", flush=True)
    started = time.monotonic()
    try:
        with log.open("wb") as output:
            result = subprocess.run([str(x) for x in cmd], cwd=cwd, env=env, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=timeout, check=False)
        code = result.returncode
    except subprocess.TimeoutExpired:
        code = 124
        with log.open("ab") as output:
            output.write(b"\nDiagnostic command exceeded its timeout.\n")
    print(f"PERF_AB_STEP {stage} exit={code} elapsed_ms={int((time.monotonic()-started)*1000)}", flush=True)
    if code and check:
        # Full build/setup logs remain local, outside the small evidence upload.
        tail = log.read_bytes()[-8000:].decode("utf-8", errors="replace")
        print(tail, file=sys.stderr, flush=True)
        raise DiagnosticError(f"{stage} failed (exit {code}); see {log.name}")
    return code


@dataclass
class Build:
    label: str
    source_sha: str
    exe: Path
    exe_hash: str
    checker: Path
    python: Path
    source: Path | None = None
    version: str | None = None
    setup: Path | None = None
    setup_hash: str | None = None

    @property
    def identity(self) -> str:
        return "built-exact-source" if self.source else "caller-supplied-exe"


def git_output(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(REPO), *args], text=True, encoding="utf-8").strip()


def build_source(label: str, source_sha: str, work: Path, evidence: Path) -> Build:
    root = work / label
    source = root / "src"
    source.mkdir(parents=True)
    logs = root / "logs"
    archive = root / "source.zip"
    if git_output("rev-parse", f"{source_sha}^{{commit}}") != source_sha.lower():
        raise DiagnosticError(f"{label}: requested exact commit not found")
    tree = git_output("rev-parse", f"{source_sha}^{{tree}}")
    subprocess.run(["git", "-C", str(REPO), "archive", "--format=zip", "--output", str(archive), source_sha], check=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(source)
    archive.unlink()

    env = child_environment()
    build_runtime = root / "build-runtime"
    build_runtime.mkdir()
    env["INVOICE_HUB_RUNTIME_DIR"] = str(build_runtime)
    venv = root / "venv"
    py = venv / "Scripts" / "python.exe"

    def step(name, cmd, timeout=600, step_env=None):
        return run_logged(cmd, cwd=source, env=step_env or env, log=logs / f"{name}.log",
                          timeout=timeout, stage=f"{label}/{name}")

    step("venv", [sys.executable, "-m", "venv", venv])
    step("pip", [py, "-m", "pip", "install", "--upgrade", "pip"])
    step("dependencies", [py, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                          "--prefer-binary", "--no-compile", *(x for lock in LOCKS for x in ("-r", lock))], 900)
    step("pip-check", [py, "-m", "pip", "check"])
    step("installed-versions", [py, "-m", "pip", "freeze", "--all"])
    # Metadata queries do not instantiate QApplication or run an executable.
    version = subprocess.check_output([str(py), "-c", "from scripts.invoice_fetch.version import VERSION; print(VERSION)"],
                                      cwd=source, env=env, text=True, encoding="utf-8").strip()
    env["INVOICE_HUB_BUILD_VERSION"] = version
    step("embedded-version", [py, "scripts/dev/write_embedded_build_version.py", "--version", version])
    step("windows-version", [py, "-m", "scripts.generate_windows_version_info", "--output", "build/windows-version-info.txt"])
    step("pyinstaller", [py, "-m", "PyInstaller", "packaging/invoice_hub_windows.spec", "--distpath", "dist",
                        "--workpath", "build/pyinstaller", "--clean", "--noconfirm"],
         step_env={**env, "PYTHONOPTIMIZE": "1"})
    exe = source / "dist" / "InvoiceHub" / "InvoiceHub.exe"
    if not exe.is_file():
        raise DiagnosticError(f"{label}: build did not produce InvoiceHub.exe")
    build = Build(label, source_sha, exe, sha256(exe), source / "scripts/check_startup_time.py", py, source, version)
    write_json(evidence / f"build-{label}.json", {
        "label": label, "identity": build.identity, "source_sha": source_sha, "source_tree": tree,
        "version": version, "exe_sha256": build.exe_hash, "checker_sha256": sha256(build.checker),
        "lock_sha256": {lock: sha256(source / lock) for lock in LOCKS},
        "installed_versions": (logs / "installed-versions.log").read_text(encoding="utf-8", errors="replace").splitlines(),
    })
    return build


def provided_build(label: str, claimed_sha: str, exe: Path, evidence: Path) -> Build:
    exe = exe.resolve(strict=True)
    if not exe.is_file() or exe.name.lower() != "invoicehub.exe":
        raise DiagnosticError(f"{label}: provide the trusted InvoiceHub.exe, not an installer")
    if any((directory / "exports").exists() for directory in (exe.parent, exe.parent / "_internal")):
        raise DiagnosticError(f"{label}: executable directory has legacy exports; use a clean diagnostic package to avoid migration")
    build = Build(label, claimed_sha, exe, sha256(exe), REPO / "scripts/check_startup_time.py", Path(sys.executable))
    write_json(evidence / f"build-{label}.json", {"label": label, "identity": build.identity,
               "claimed_source_sha": claimed_sha, "exe_sha256": build.exe_hash,
               "checker_sha256": sha256(build.checker)})
    return build


def installer_registrations() -> list[tuple[str, str]]:
    """Read only the precise known Inno registration, in both registry views."""
    import winreg

    records = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, UNINSTALL_KEY, 0, winreg.KEY_READ | view) as key:
                    def read(name):
                        try:
                            return str(winreg.QueryValueEx(key, name)[0])
                        except FileNotFoundError:
                            return ""
                    records.append((read("InstallLocation"), read("DisplayVersion")))
            except FileNotFoundError:
                pass
    return records


def require_no_installation() -> None:
    if installer_registrations():
        raise DiagnosticError("Existing Invoice Hub Inno registration; refusing to install over it")
    for folder, suffix in (("LOCALAPPDATA", "Programs/InvoiceHub"), ("ProgramFiles", "InvoiceHub"),
                           ("ProgramFiles(x86)", "InvoiceHub")):
        if os.environ.get(folder) and (Path(os.environ[folder]) / suffix).exists():
            raise DiagnosticError("Existing default Invoice Hub installation directory; refusing disposable install")


def find_iscc(value: str | None) -> Path:
    found = value or shutil.which("iscc")
    if not found and os.environ.get("ProgramFiles(x86)"):
        found = str(Path(os.environ["ProgramFiles(x86)"]) / "Inno Setup 6" / "ISCC.exe")
    if not found or not Path(found).is_file():
        raise DiagnosticError("Inno Setup compiler not found; install Inno Setup 6 or specify --iscc")
    return Path(found).resolve()


def record_iscc(iscc: Path, evidence: Path) -> None:
    info = {"sha256": sha256(iscc)}
    try:
        result = subprocess.run([str(iscc), "/?"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=child_environment(), timeout=20, check=False)
        info["version_banner"] = result.stdout.decode("utf-8", errors="replace").splitlines()[:8]
    except (OSError, subprocess.TimeoutExpired) as exc:
        info["version_banner_error"] = type(exc).__name__
    write_json(evidence / "inno-compiler.json", info)


def build_installer(build: Build, iscc: Path, work: Path, evidence: Path) -> None:
    source = build.source
    assert source is not None and build.version is not None
    env = child_environment()
    logs = work / build.label / "logs"
    run_logged([build.python, "scripts/dev/generate_installer_ownership.py", "include", "--current-dir", "dist/InvoiceHub",
                "--legacy-manifest", "packaging/legacy/v0.1.5-rc1-files.txt", "--legacy-manifest", "packaging/legacy/v0.1.5-rc2-files.txt",
                "--output", "packaging/legacy/installer_ownership.issinc", "--current-manifest-output", "build/current-installer-files.txt"],
               cwd=source, env=env, log=logs / "ownership.log", timeout=120, stage=f"{build.label}/ownership")
    run_logged([iscc, "packaging/invoice_hub_windows.iss", f"/DAppVersion={build.version}",
                f"/DSourceDir={build.exe.parent}", f"/DOutputDir={source / 'dist'}"],
               cwd=source, env=env, log=logs / "iscc.log", timeout=600, stage=f"{build.label}/iscc")
    build.setup = source / "dist" / f"InvoiceHub-{build.version}-win64-setup.exe"
    if not build.setup.is_file():
        raise DiagnosticError(f"{build.label}: Inno Setup did not produce the expected installer")
    build.setup_hash = sha256(build.setup)
    write_json(evidence / f"installer-{build.label}.json", {"label": build.label, "source_sha": build.source_sha,
               "setup_sha256": build.setup_hash, "source_exe_sha256": build.exe_hash, "version": build.version})


def same_path(left: str, right: Path) -> bool:
    return bool(left) and os.path.normcase(os.path.abspath(left)) == os.path.normcase(str(right.resolve()))


@contextmanager
def installed_executable(build: Build, sample_root: Path, record: dict):
    """Fresh real Inno install/uninstall. Never repair/remove an existing install."""
    require_no_installation()
    assert build.setup is not None
    install_dir = sample_root / "install"
    if install_dir.exists():
        raise DiagnosticError("Diagnostic install directory already exists")
    setup_log = sample_root / "setup-inno.log"
    record["setup_sha256"] = build.setup_hash
    record["install_verified"] = False
    record["uninstall_verified"] = False
    try:
        code = run_logged([build.setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/MERGETASKS=!desktopicon",
                           f"/DIR={install_dir}", f"/LOG={setup_log}"], cwd=sample_root, env=child_environment(),
                          log=sample_root / "setup-process.log", timeout=300, stage=f"{record['sample']}/install", check=False)
        record["setup_exit"] = code
        if code:
            raise DiagnosticError(f"Inno setup failed (exit {code}); see setup-inno.log")
        exe = install_dir / "InvoiceHub.exe"
        registrations = installer_registrations()
        if (not registrations or not all(same_path(path, install_dir) and version == build.version for path, version in registrations)
                or not exe.is_file() or sha256(exe) != build.exe_hash):
            raise DiagnosticError("Installed location, version or executable hash did not match the exact built package")
        # Match the release install smoke: the version-only entry exits before
        # importing the GUI. It precedes the first installed desktop launch.
        version_path = sample_root / "installed-version.json"
        run_logged([exe, "--version-probe-file", version_path], cwd=sample_root, env=child_environment(),
                   log=sample_root / "version-probe.log", timeout=30, stage=f"{record['sample']}/version-probe")
        version_probe = json.loads(version_path.read_text(encoding="utf-8"))
        if (version_probe.get("contract") != "invoice_hub_build_version_v1" or
                version_probe.get("app_version") != f"v{build.version}"):
            raise DiagnosticError("Installed embedded version does not match the exact built source")
        record["installed_version_probe"] = version_probe
        record["installed_exe_sha256"] = build.exe_hash
        record["install_verified"] = True
        yield exe
    finally:
        # Only invoke the uninstaller if the registration belongs to our newly
        # created path. No registry deletion, arbitrary uninstall command, or
        # recursive removal of an existing application is performed.
        registrations = installer_registrations()
        if registrations and all(same_path(path, install_dir) for path, _ in registrations):
            uninstallers = [p for p in install_dir.glob("unins*.exe") if p.is_file()
                            and re.fullmatch(r"unins\d{3}\.exe", p.name, re.I)
                            and p.resolve().parent == install_dir.resolve()]
            if len(uninstallers) != 1:
                raise DiagnosticError("Owned install did not contain exactly one known Inno uninstaller; cleanup requires inspection")
            code = run_logged([uninstallers[0], "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                              cwd=sample_root, env=child_environment(), log=sample_root / "uninstall.log", timeout=300,
                              stage=f"{record['sample']}/uninstall", check=False)
            record["uninstall_exit"] = code
            if code:
                raise DiagnosticError(f"Diagnostic uninstall failed (exit {code})")
            for _ in range(600):
                if not install_dir.exists() and not installer_registrations():
                    break
                time.sleep(0.1)
        if install_dir.exists() or installer_registrations():
            raise DiagnosticError("Diagnostic install cleanup not verified; stop further installs without deleting unknown state")
        record["uninstall_verified"] = True


def measure(build: Build, exe: Path, sample_root: Path, evidence: Path, record: dict,
            *, etw_collector: Path | None = None, mapped_files: bool = False) -> None:
    env = sample_environment(sample_root / "runtime")
    log = evidence / f"{record['sample']}.log"
    command = [build.python, build.checker, exe, "--threshold", str(record["threshold_ms"]), "--output-json"]
    observer = None
    if record.get("native_observation_requested"):
        try:
            observer = observer_module()
        except Exception as exc:
            record["native_observer"] = {"observer_error": f"Could not import observer: {type(exc).__name__}"}
    capture = None
    if etw_collector is not None:
        try:
            spec = importlib.util.spec_from_file_location("_ab_etw", Path(__file__).with_name("windows_startup_etw.py"))
            etw = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(etw)
            capture = etw.EtwCapture(etw_collector, sample_root / "etw-control",
                                     evidence / f"{record['sample']}.etw.json", mapped_files=mapped_files)
            capture.start()
        except Exception as exc:
            record["etw"] = {"status": "unavailable", "error": f"ETW bridge: {type(exc).__name__}"}
    try:
        if observer is not None:
            print(f"PERF_AB_STEP {record['sample']} started with read-only native observation", flush=True)
            extra = {"etw": capture} if capture is not None else {}
            record["checker_exit"], record["native_observer"] = observer.run_observed_checker(
                command, cwd=sample_root, env=env, log=log, exe=exe,
                trace_path=evidence / f"{record['sample']}.native-trace.json", **extra)
        else:
            record["checker_exit"] = run_logged(command, cwd=sample_root, env=env, log=log, timeout=75,
                                               stage=record["sample"], check=False)
    finally:
        if capture is not None:
            try:
                record["etw"] = capture.finish(record.get("native_observer", {}))
            except Exception as exc:
                record["etw"] = {"status": "unavailable", "error": f"ETW finish: {type(exc).__name__}"}
    raw = list((sample_root / "bench-local/results").glob("startup_metrics_*.json"))
    if len(raw) == 1:
        target = evidence / f"{record['sample']}.metrics.json"
        shutil.copyfile(raw[0], target)
        record["metrics"] = json.loads(target.read_text(encoding="utf-8"))
        spec = importlib.util.spec_from_file_location("_ab_official_checker", build.checker)
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        record["truth_errors"] = checker._probe_truth_errors(record["metrics"])
    else:
        record["truth_errors"] = ["No unique raw metrics JSON from the release checker"]
    # The official checker, not a median or wall-time reinterpretation, makes
    # each gate decision. Missing raw evidence never counts as a success.
    record["gate_pass"] = record["checker_exit"] == 0 and not record["truth_errors"]


def collect_sample(build: Build, mode: str, ordinal: int, work: Path, evidence: Path,
                   *, fresh_install: bool, observe_native: bool = False,
                   etw_collector: Path | None = None, mapped_files: bool = False) -> dict:
    sample = f"{mode}-{ordinal:02d}-{build.label}"
    root = work / "samples" / sample
    root.mkdir(parents=True)
    record = {"sample": sample, "index": ordinal, "label": build.label, "mode": mode,
              "identity": build.identity, "source_sha": build.source_sha if build.source else None,
              "claimed_source_sha": build.source_sha if not build.source else None, "exe_sha256": build.exe_hash,
              "threshold_ms": THRESHOLDS[mode], "fresh_inno_install": fresh_install,
              "started_utc": utc_now(), "checker_exit": None, "gate_pass": False, "metrics": None}
    if observe_native:
        record["native_observation_requested"] = True
    if etw_collector is not None:
        record["etw_requested"] = True
    extra = {"etw_collector": etw_collector} if etw_collector is not None else {}
    if mapped_files:
        record["mapped_files_requested"] = True
        extra["mapped_files"] = True
    try:
        if fresh_install:
            with installed_executable(build, root, record) as exe:
                measure(build, exe, root, evidence, record, **extra)
        else:
            measure(build, build.exe, root, evidence, record, **extra)
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        if fresh_install:
            # On an infrastructure failure the small uploaded evidence must
            # still contain enough Inno context to investigate the attempt.
            tails = []
            for name in ("setup-inno.log", "setup-process.log", "version-probe.log", "uninstall.log"):
                path = root / name
                if path.is_file():
                    data = path.read_bytes()[-12_000:]
                    encoding = "utf-16-le" if b"\x00" in data[:128] else "utf-8"
                    tails.append(f"--- {name} (tail) ---\n" + data.decode(encoding, errors="replace"))
            if tails:
                (evidence / f"{sample}.install-failure.log").write_text("\n".join(tails), encoding="utf-8")
    record["finished_utc"] = utc_now()
    with (evidence / "samples.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    print("PERF_AB_SAMPLE " + json.dumps(record, ensure_ascii=False, separators=(",", ":")), flush=True)
    return record


def summarize(records: list[dict], expected: int) -> dict:
    groups = {}
    for mode in THRESHOLDS:
        for label in "ABF":
            selected = [r for r in records if r["mode"] == mode and r["label"] == label]
            if not selected:
                continue
            metrics = [r["metrics"] for r in selected if r.get("metrics") and not r.get("truth_errors")]
            totals = [m["TOTAL_STARTUP_MS"] for m in metrics if m.get("TOTAL_STARTUP_MS", 0) > 0]
            stages = [m["LAUNCH_STAGE_MS"] for m in metrics if "LAUNCH_STAGE_MS" in m]
            shows = [s["splash_shown"] - s["splash_constructed"] for s in stages
                     if "splash_shown" in s and "splash_constructed" in s]
            groups[f"{mode}-{label}"] = {"samples": len(selected), "gate_passes": sum(r["gate_pass"] for r in selected),
                                         "total_startup_ms": totals, "total_median_ms": statistics.median(totals) if totals else None,
                                         "splash_show_ms": shows, "splash_show_median_ms": statistics.median(shows) if shows else None}
    return {"expected_samples": expected, "recorded_samples": len(records), "groups": groups,
            "all_gates_passed": len(records) == expected and all(r["gate_pass"] and not r.get("error") for r in records)}


def native_qt_samples(builds: dict[str, Build], work: Path, evidence: Path) -> bool:
    """After all frozen samples, compare isolated native Qt first-window variants."""
    successful = True
    helper = Path(__file__).with_name("windows_startup_qt_probe.py")
    for variant, order in (("plain", "AB"), ("label", "BA"), ("production-splash", "AB")):
        for label in order:
            if label not in builds:
                continue
            build = builds[label]
            root = work / "native-qt" / f"{variant}-{label}"
            root.mkdir(parents=True)
            output = evidence / f"qt-{variant}-{label}.json"
            code = run_logged([build.python, helper, "--source", build.source, "--variant", variant, "--output", output],
                              cwd=root, env=sample_environment(root / "runtime"), log=evidence / f"qt-{variant}-{label}.log",
                              timeout=60, stage=f"native-qt/{variant}/{label}", check=False)
            data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else None
            print("PERF_AB_QT " + json.dumps({"label": label, "source_sha": build.source_sha, "variant": variant,
                                                   "exit": code, "metrics": data}, ensure_ascii=False), flush=True)
            successful = successful and code == 0 and data is not None
    return successful


def observer_module():
    if __package__:
        from . import windows_startup_observer
    else:
        import windows_startup_observer
    return windows_startup_observer


def record_system_state(evidence: Path, phase: str) -> None:
    try:
        state = observer_module().system_state()
    except Exception as exc:
        state = {"unavailable": type(exc).__name__}
    payload = {"phase": phase, "utc": utc_now(), **state}
    print("PERF_AB_SYSTEM_STATE " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)
    try:
        write_json(evidence / f"system-{phase}.json", payload)
    except OSError as exc:
        print(f"PERF_AB_OBSERVER_STATE_ERROR {phase} {type(exc).__name__}", flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory for builds, raw logs and evidence")
    parser.add_argument("--candidate-sha", default=CANDIDATE)
    parser.add_argument("--baseline-sha", default=BASELINE)
    parser.add_argument("--mode", choices=("portable", "installed", "both"), default="portable")
    parser.add_argument("--order", type=sample_order, default="ABBA,BAAB")
    parser.add_argument("--disposable-runner", action="store_true", help="Explicitly permit actual Inno install/uninstall on a clean disposable Windows host")
    parser.add_argument("--iscc", help="Path to Inno Setup 6 ISCC.exe")
    parser.add_argument("--candidate-exe", type=Path, help="Offline comparison: trusted existing A executable")
    parser.add_argument("--baseline-exe", type=Path, help="Offline comparison: trusted existing B executable")
    parser.add_argument("--native-qt", action="store_true", help="After frozen samples, run diagnostic-only native Qt window variants")
    parser.add_argument("--baseline-first", action="store_true", help="Build only historical B; observe two consecutive native startup samples")
    parser.add_argument("--optimized-sha", help="Compare exact optimized F with A/B, including a first-position ETW sample")
    parser.add_argument("--etw-collector", type=Path, help="Built StartupEtw.dll for the three-revision diagnostic")
    parser.add_argument("--etw-focus", action="store_true", help="After an infrastructure correction, trace only F and historical B twice")
    parser.add_argument("--mapped-file-focus", action="store_true", help="Trace only the exact current optimized package twice with query-time mapped-file observations")
    args = parser.parse_args(argv)
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"} or sys.maxsize <= 2**32:
        parser.error("This diagnostic requires native Windows x64 and 64-bit Python")
    if sys.version_info[:2] != (3, 11):
        parser.error("Use Python 3.11, matching the release build")
    if any(not re.fullmatch(r"[0-9a-fA-F]{40}", rev) for rev in (args.candidate_sha, args.baseline_sha)):
        parser.error("Both source revisions must be full commit SHAs")
    provided = bool(args.candidate_exe or args.baseline_exe)
    if provided and not (args.candidate_exe and args.baseline_exe):
        parser.error("Provide both existing executables for offline comparison")
    if provided and (args.mode == "both" or args.native_qt or args.disposable_runner):
        parser.error("Provided executables support one declared mode, without installing or source Qt probes")
    if args.baseline_first and (provided or args.mode != "portable" or args.disposable_runner):
        parser.error("--baseline-first uses only a freshly built baseline portable package, without installation")
    three_way = args.optimized_sha is not None
    if three_way:
        revisions = (args.candidate_sha, args.baseline_sha, args.optimized_sha)
        if (provided or args.baseline_first or args.mode == "installed" or
                not all(re.fullmatch(r"[0-9a-fA-F]{40}", rev) for rev in revisions) or
                len({rev.lower() for rev in revisions}) != 3 or
                args.etw_collector is None or not args.etw_collector.resolve().is_file()):
            parser.error("Three-revision comparison requires three distinct exact source SHAs and a built ETW collector, with portable or both modes")
    elif args.etw_collector is not None:
        parser.error("--etw-collector requires --optimized-sha")
    if args.etw_focus and (not three_way or args.mode != "portable" or args.native_qt or args.disposable_runner):
        parser.error("--etw-focus requires the exact optimization and portable ETW comparison")
    if args.mapped_file_focus and (not three_way or args.etw_focus or args.mode != "portable" or args.native_qt or args.disposable_runner):
        parser.error("--mapped-file-focus requires one exact optimized portable package and ETW collector")
    real_install = not provided and args.mode in {"installed", "both"}
    if real_install and not args.disposable_runner:
        parser.error("Real Inno samples require --disposable-runner on a clean disposable Windows host")
    output = args.output_dir.resolve()
    if output.exists():
        parser.error("Output directory must not already exist")
    work, evidence = output / "work", output / "evidence"
    work.mkdir(parents=True)
    evidence.mkdir()
    modes = ("portable", "installed") if args.mode == "both" else (args.mode,)
    order = "BB" if args.baseline_first else args.order
    traced_order = "FF" if args.mapped_file_focus else "FFBB" if args.etw_focus else "FFABBAF"
    control_order = "" if args.etw_focus or args.mapped_file_focus else "BAFFAB"
    if three_way:
        order = traced_order + control_order
    records = []
    expected = len(order) + (2 if "installed" in modes else 0) if three_way else len(order) * len(modes)
    error = None
    qt_ok = not args.native_qt
    write_json(evidence / "host.json", {"started_utc": utc_now(), "platform": platform.platform(),
               "machine": platform.machine(), "python": sys.version, "logical_cpus": os.cpu_count(),
               "runner": {k: os.environ.get(k) for k in ("RUNNER_OS", "RUNNER_ARCH", "RUNNER_ENVIRONMENT", "ImageOS", "ImageVersion")},
               "native_qt_platform": "windows", "order": order, "modes": modes, "thresholds_ms": THRESHOLDS,
               "diagnostic_protocol": "mapped-file-focus" if args.mapped_file_focus else "focused-etw" if args.etw_focus else "three-way-etw" if three_way else "baseline-first" if args.baseline_first else "balanced-ab",
               "optimized_sha": args.optimized_sha,
               "traced_portable_order": traced_order if three_way else None,
               "untraced_portable_order": control_order if three_way else None,
               "installed_order": "FF" if three_way and "installed" in modes else None,
               "candidate_sha": args.candidate_sha, "baseline_sha": args.baseline_sha,
               "provided_executables": provided, "fresh_inno_install": real_install,
               "runtime_policy": "fresh empty database/config defaults, synthetic workbench migration marker, null keyring",
               "cache_policy": "new process/runtime per sample; no OS cache flushing or intentional Qt warmup"})
    try:
        if real_install:
            require_no_installation()
            iscc = find_iscc(args.iscc)
            record_iscc(iscc, evidence)
        if provided:
            builds = {"A": provided_build("A", args.candidate_sha, args.candidate_exe, evidence),
                      "B": provided_build("B", args.baseline_sha, args.baseline_exe, evidence)}
        elif args.baseline_first:
            builds = {"B": build_source("B", args.baseline_sha.lower(), work, evidence)}
            record_system_state(evidence, "before-first")
        elif three_way:
            revisions = [("F", args.optimized_sha)]
            if not args.mapped_file_focus:
                if not args.etw_focus:
                    revisions.append(("A", args.candidate_sha))
                revisions.append(("B", args.baseline_sha))
            builds = {label: build_source(label, rev.lower(), work, evidence) for label, rev in revisions}
            record_system_state(evidence, "before-first")
        else:
            builds = {label: build_source(label, rev.lower(), work, evidence) for label, rev in
                      (("A", args.candidate_sha), ("B", args.baseline_sha))}
        for mode in modes:
            lane_order = "FF" if three_way and mode == "installed" else order
            if mode == "installed" and real_install:
                for build in (builds["F"],) if three_way else builds.values():
                    build_installer(build, iscc, work, evidence)
            for ordinal, label in enumerate(lane_order, 1):
                trace_sample = three_way and ((mode == "portable" and ordinal <= len(traced_order)) or
                                              (mode == "installed" and ordinal == 1))
                observe_native = args.baseline_first or trace_sample
                extra = {"etw_collector": args.etw_collector.resolve()} if trace_sample else {}
                if trace_sample and args.mapped_file_focus:
                    extra["mapped_files"] = True
                record = collect_sample(builds[label], mode, ordinal, work, evidence,
                                        fresh_install=real_install and mode == "installed", observe_native=observe_native, **extra)
                records.append(record)
                if observe_native and mode == "portable" and ordinal == 1:
                    record_system_state(evidence, "after-first")
                if record.get("error") and record["fresh_inno_install"]:
                    raise DiagnosticError("Installed sample infrastructure/cleanup failure; stop further installs")
        if args.native_qt:
            qt_ok = native_qt_samples(builds, work, evidence)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        print("PERF_AB_ERROR " + error, file=sys.stderr, flush=True)
    summary = {**summarize(records, expected), "error": error, "native_qt_requested": args.native_qt,
               "native_qt_completed": qt_ok if args.native_qt else None, "finished_utc": utc_now()}
    if three_way:
        statuses = [r.get("etw", {}).get("status", "unavailable") for r in records if r.get("etw_requested")]
        summary["etw_samples"] = {status: statuses.count(status) for status in ("complete", "partial", "unavailable")}
        traced = [record for record in records if record.get("etw_requested")]
        controls = [record for record in records if not record.get("etw_requested")]
        observed = [r for r in traced if r.get("etw", {}).get("status") in ("complete", "partial")
                    and r["etw"].get("raw_scheduler_point_count", 0) > 0]
        summary["etw_evidence_collected"] = bool(observed)
        summary["etw_samples_with_verified_scheduler_points"] = len(observed)
        first = next((r for r in traced if r["mode"] == "portable" and r.get("index") == 1), {})
        first_etw = first.get("etw", {})
        native_events = first.get("native_observer", {}).get("events", {})
        splash_tid = native_events.get("splash-like_seen", {}).get("window_thread_id")
        visible_tid = native_events.get("splash-like_visible", {}).get("window_thread_id")
        ui = next((t for t in first_etw.get("ui_threads", [])
                   if splash_tid and splash_tid == visible_tid == t.get("thread_id")), {})
        splash_phase = ui.get("phases", {}).get("splash-like_seen_to_splash-like_visible", {})
        summary["optimized_first_etw"] = {
            "status": first_etw.get("status", "unavailable"),
            "verified_scheduler_points": first_etw.get("raw_scheduler_point_count", 0),
            "splash_visibility_bounds": first_etw.get("coverage", {}).get("splash_visibility_bounds", False),
            "ui_splash_scheduler_covered_ms": (
                splash_phase["off_cpu_ms"] + splash_phase["completed_running_ms"] if splash_phase else None
            ),
        }
        summary["traced_groups"] = summarize(traced, len(traced_order) + int("installed" in modes))["groups"]
        summary["untraced_groups"] = summarize(controls, len(control_order) + int("installed" in modes))["groups"]
        if args.mapped_file_focus:
            summary["mapped_file_samples"] = [{"sample": r.get("sample"),
                "identity_verified": r.get("etw", {}).get("mapped_file_lookup", {}).get("coverage", {}).get("verified", False),
                "observed_queries": r.get("etw", {}).get("mapped_file_lookup", {}).get("observed_queries", 0),
                "retained_faults": r.get("etw", {}).get("mapped_file_lookup", {}).get("retained_faults", 0)} for r in traced]
    write_json(evidence / "summary.json", summary)
    print("PERF_AB_SUMMARY " + json.dumps(summary, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0 if summary["all_gates_passed"] and error is None and qt_ok and summary.get("etw_evidence_collected", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
