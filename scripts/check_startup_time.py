#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/check_startup_time.py — Invoice Hub 启动性能门槛校验器。

发布门槛只接受带版本标识的“完整主窗口首次 Qt Paint 事件已完成”探针结果。
probe JSON 为权威数据源，stdout 仅作为兼容 fallback。外部进程 wall time
继续记录用于诊断探针退出/进程收尾开销，但不参与“启动到首次 Paint”的
3000 ms 发布门槛。该探针证明 Qt 主窗口已完成一次 Paint 事件，不把它描述
成操作系统合成器或显示器已经完成物理呈现。

使用方式：
    # 验证打包后的 PyInstaller 可执行文件：
    python scripts/check_startup_time.py dist/InvoiceHub/InvoiceHub.exe

    # 在开发模式下直接运行 Python 模块验证：
    python scripts/check_startup_time.py --python

    # 自定义超时门槛（毫秒）：
    python scripts/check_startup_time.py dist/InvoiceHub/InvoiceHub.exe --threshold 3000

退出码：
    0  — 已观察到真实主窗口首次 Qt Paint 完成，且启动时间在阈值内
    1  — 探针证据无效、启动超时、程序异常退出或超过阈值
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ── Default thresholds ────────────────────────────────────────────────
LOCAL_THRESHOLD_MS = 2000
CI_THRESHOLD_MS = 3000
PROBE_TIMEOUT_S = 30
PROBE_CONTRACT = "main_window_first_paint_v1"

# ── Compatibility stdout patterns ────────────────────────────────────
_RE_STARTUP_MS = re.compile(r"^STARTUP_MS=(\d+)", re.MULTILINE)
_RE_APP_INIT_MS = re.compile(r"^APP_INIT_MS=(\d+)", re.MULTILINE)
_RE_SHOW_MS = re.compile(r"^MAIN_WINDOW_SHOW_MS=(\d+)", re.MULTILINE)
_RE_DB_OPEN_MS = re.compile(r"^DB_OPEN_MS=(\d+)", re.MULTILINE)
_RE_GUI_INIT_MS = re.compile(r"^GUI_INIT_MS=(\d+)", re.MULTILINE)
_RE_FIRST_LOAD_MS = re.compile(r"^FIRST_LOAD_MS=(\d+)", re.MULTILINE)
_RE_FIRST_PAINT_MS = re.compile(r"^FIRST_PAINT_MS=(\d+)", re.MULTILINE)
_RE_TOTAL_STARTUP_MS = re.compile(r"^TOTAL_STARTUP_MS=(\d+)", re.MULTILINE)
_RE_PROBE_CONTRACT = re.compile(r"^PROBE_CONTRACT=([^\r\n]+)", re.MULTILINE)
_RE_QT_PAINT_COMPLETED = re.compile(
    r"^QT_PAINT_EVENT_COMPLETED=([01]|True|False)",
    re.MULTILINE | re.IGNORECASE,
)

_NUMERIC_METRICS = (
    "APP_INIT_MS",
    "DB_OPEN_MS",
    "MAIN_WINDOW_SHOW_MS",
    "STARTUP_MS",
    "GUI_INIT_MS",
    "FIRST_LOAD_MS",
    "FIRST_PAINT_MS",
    "TOTAL_STARTUP_MS",
)


def _build_cmd(exe_path: Path | None, python_mode: bool) -> list[str]:
    if python_mode:
        return [
            sys.executable,
            "-m",
            "scripts.invoice_fetch",
            "desktop",
            "--startup-probe",
        ]
    if exe_path is None:
        print("ERROR: must supply an EXE path or use --python", file=sys.stderr)
        raise SystemExit(1)
    return [str(exe_path), "desktop", "--startup-probe"]


def _stdout_int(pattern: re.Pattern[str], combined: str, current: int) -> int:
    if current >= 0:
        return current
    match = pattern.search(combined)
    return int(match.group(1)) if match else -1


def _stdout_bool(pattern: re.Pattern[str], combined: str, current: bool) -> bool:
    if current:
        return True
    match = pattern.search(combined)
    if not match:
        return False
    return match.group(1).lower() in {"1", "true"}


def run_probe(cmd: list[str]) -> dict[str, object]:
    """Run the startup probe and return its evidence plus external wall time."""
    print(f"Running probe: {' '.join(cmd)}")

    fd, temp_path_str = tempfile.mkstemp(suffix="_startup_probe.json")
    os.close(fd)
    temp_path = Path(temp_path_str)

    custom_env = os.environ.copy()
    custom_env["INVOICE_HUB_STARTUP_PROBE"] = "1"
    custom_env["INVOICE_HUB_STARTUP_PROBE_FILE"] = str(temp_path)

    t_start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_S,
            creationflags=0,
            env=custom_env,
        )
    except subprocess.TimeoutExpired:
        temp_path.unlink(missing_ok=True)
        print(
            f"ERROR: probe timed out after {PROBE_TIMEOUT_S}s "
            "(the main-window first Qt Paint event was not observed in time)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except FileNotFoundError as exc:
        temp_path.unlink(missing_ok=True)
        print(f"ERROR: executable not found — {exc}", file=sys.stderr)
        raise SystemExit(1)

    process_wall_ms = int((time.perf_counter() - t_start) * 1000)
    metrics: dict[str, object] = {key: -1 for key in _NUMERIC_METRICS}
    metrics.update(
        {
            "PROBE_CONTRACT": "",
            "QT_PAINT_EVENT_COMPLETED": False,
            "PROCESS_WALL_MS": process_wall_ms,
            "PROCESS_RETURN_CODE": int(result.returncode),
        }
    )

    # JSON is authoritative because the child writes it only after the Paint
    # event has returned to the Qt event loop.
    if temp_path.exists() and temp_path.stat().st_size > 0:
        try:
            data = json.loads(temp_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in _NUMERIC_METRICS:
                    value = data.get(key)
                    if isinstance(value, int) and not isinstance(value, bool):
                        metrics[key] = value
                contract = data.get("PROBE_CONTRACT")
                if isinstance(contract, str):
                    metrics["PROBE_CONTRACT"] = contract
                metrics["QT_PAINT_EVENT_COMPLETED"] = (
                    data.get("QT_PAINT_EVENT_COMPLETED") is True
                )
                print("Parsed metrics successfully from probe JSON file.")
        except Exception as exc:
            print(f"WARNING: failed to parse probe JSON file — {exc}", file=sys.stderr)
    temp_path.unlink(missing_ok=True)

    # stdout fallback keeps diagnostics usable if the JSON path could not be
    # written, but the same contract/paint-event validation still applies.
    combined = (result.stdout or "") + (result.stderr or "")
    patterns = {
        "APP_INIT_MS": _RE_APP_INIT_MS,
        "DB_OPEN_MS": _RE_DB_OPEN_MS,
        "MAIN_WINDOW_SHOW_MS": _RE_SHOW_MS,
        "STARTUP_MS": _RE_STARTUP_MS,
        "GUI_INIT_MS": _RE_GUI_INIT_MS,
        "FIRST_LOAD_MS": _RE_FIRST_LOAD_MS,
        "FIRST_PAINT_MS": _RE_FIRST_PAINT_MS,
        "TOTAL_STARTUP_MS": _RE_TOTAL_STARTUP_MS,
    }
    for key, pattern in patterns.items():
        metrics[key] = _stdout_int(pattern, combined, int(metrics[key]))

    if not metrics["PROBE_CONTRACT"]:
        match = _RE_PROBE_CONTRACT.search(combined)
        if match:
            metrics["PROBE_CONTRACT"] = match.group(1).strip()
    metrics["QT_PAINT_EVENT_COMPLETED"] = _stdout_bool(
        _RE_QT_PAINT_COMPLETED,
        combined,
        bool(metrics["QT_PAINT_EVENT_COMPLETED"]),
    )

    if _probe_truth_errors(metrics):
        print("Probe stdout:", (result.stdout or "")[:1000], file=sys.stderr)
        print("Probe stderr:", (result.stderr or "")[:1000], file=sys.stderr)

    return metrics


def _probe_truth_errors(metrics: dict[str, object]) -> list[str]:
    """Return fail-closed evidence errors for a completed Qt first-paint event."""
    errors: list[str] = []
    if metrics.get("PROBE_CONTRACT") != PROBE_CONTRACT:
        errors.append(f"PROBE_CONTRACT must be {PROBE_CONTRACT}")
    if metrics.get("QT_PAINT_EVENT_COMPLETED") is not True:
        errors.append("QT_PAINT_EVENT_COMPLETED must be true")
    if int(metrics.get("PROCESS_RETURN_CODE", -1)) != 0:
        errors.append("probe process must exit with code 0")

    show_ms = int(metrics.get("MAIN_WINDOW_SHOW_MS", -1))
    paint_ms = int(metrics.get("FIRST_PAINT_MS", -1))
    total_ms = int(metrics.get("TOTAL_STARTUP_MS", -1))
    startup_ms = int(metrics.get("STARTUP_MS", -1))

    if show_ms < 0:
        errors.append("MAIN_WINDOW_SHOW_MS is missing")
    if paint_ms <= 0:
        errors.append("FIRST_PAINT_MS must be greater than zero")
    if show_ms >= 0 and paint_ms >= 0 and paint_ms < show_ms:
        errors.append("FIRST_PAINT_MS cannot precede MAIN_WINDOW_SHOW_MS")
    if total_ms <= 0:
        errors.append("TOTAL_STARTUP_MS must be greater than zero")
    if total_ms >= 0 and paint_ms >= 0 and total_ms < paint_ms:
        errors.append("TOTAL_STARTUP_MS cannot be less than FIRST_PAINT_MS")
    if startup_ms != total_ms:
        errors.append("STARTUP_MS must equal the Qt first-paint TOTAL_STARTUP_MS contract")
    return errors


def _release_gate_ms(metrics: dict[str, object]) -> int:
    """Return the metric governed by the first-paint startup SLO.

    PROCESS_WALL_MS includes work after the probe has already persisted valid
    first-paint evidence (Qt/app exit and interpreter/process teardown). It is
    useful diagnostic evidence but is not part of the startup-readiness
    contract.
    """
    return int(metrics.get("TOTAL_STARTUP_MS", -1))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Invoice Hub 启动性能门槛校验器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "exe",
        nargs="?",
        metavar="EXE_PATH",
        help="Path to InvoiceHub.exe (e.g. dist/InvoiceHub/InvoiceHub.exe)",
    )
    parser.add_argument(
        "--python",
        action="store_true",
        help="Run via Python module instead of built EXE (development mode)",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help=f"Startup threshold in ms (default: {LOCAL_THRESHOLD_MS} local / {CI_THRESHOLD_MS} CI)",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Use CI threshold instead of local threshold",
    )
    parser.add_argument(
        "--output-json",
        action="store_true",
        help="Output results to JSON file in bench-local/results/",
    )
    args = parser.parse_args()

    threshold = args.threshold
    if threshold is None:
        threshold = CI_THRESHOLD_MS if args.ci else LOCAL_THRESHOLD_MS
    if threshold <= 0:
        parser.error("--threshold must be greater than zero")

    exe_path = Path(args.exe) if args.exe else None
    if exe_path and not exe_path.exists():
        print(f"ERROR: EXE not found: {exe_path}", file=sys.stderr)
        raise SystemExit(1)

    metrics = run_probe(_build_cmd(exe_path, args.python))
    truth_errors = _probe_truth_errors(metrics)

    total_startup_ms = int(metrics["TOTAL_STARTUP_MS"])
    process_wall_ms = int(metrics["PROCESS_WALL_MS"])
    process_wall_overhead_ms = max(0, process_wall_ms - total_startup_ms)
    gate_ms = _release_gate_ms(metrics)

    print()
    print("+----------------------------------------------------------------+")
    print("|         Invoice Hub 桌面端启动耗时性能指标报告         |")
    print("+--------------------------------------+-------------------------+")
    print("| 阶段名称                             | 耗时 (毫秒)             |")
    print("+--------------------------------------+-------------------------+")
    print(f"| APP_INIT_MS (GUI模块完整载入)         | {metrics['APP_INIT_MS']:<23} |")
    print(f"| DB_OPEN_MS (SQLite数据库加载与迁移)   | {metrics['DB_OPEN_MS']:<23} |")
    print(f"| GUI_INIT_MS (首屏工作台构建)          | {metrics['GUI_INIT_MS']:<23} |")
    print(f"| FIRST_LOAD_MS (首屏数据载入)          | {metrics['FIRST_LOAD_MS']:<23} |")
    print(f"| MAIN_WINDOW_SHOW_MS (主窗口Show事件)  | {metrics['MAIN_WINDOW_SHOW_MS']:<23} |")
    print(f"| FIRST_PAINT_MS (首次Qt Paint已返回)   | {metrics['FIRST_PAINT_MS']:<23} |")
    print(f"| TOTAL_STARTUP_MS (GUI首次Paint总耗时) | {total_startup_ms:<23} |")
    print(f"| PROCESS_WALL_MS (探针进程wall含收尾)  | {process_wall_ms:<23} |")
    print(f"| WALL_OVERHEAD_MS (Paint后探针收尾)    | {process_wall_overhead_ms:<23} |")
    print("+--------------------------------------+-------------------------+")
    print(f"| 发布门槛判定耗时 (first-paint total) | {gate_ms:<23} |")
    print(f"| 超时判定门槛 (Threshold Limit)        | {threshold:<23} |")
    print("+----------------------------------------------------------------+")
    print(f"Probe contract: {metrics['PROBE_CONTRACT']}")
    print(f"Qt paint event completed: {metrics['QT_PAINT_EVENT_COMPLETED']}")
    print("Presentation boundary: Qt Paint event completed; OS compositor/display presentation is not asserted.")
    print("Process wall boundary: diagnostic only; includes probe/app/process teardown after first-paint evidence.")
    print()

    if args.output_json:
        bench_dir = Path("bench-local/results")
        bench_dir.mkdir(parents=True, exist_ok=True)
        json_path = bench_dir / f"startup_metrics_{int(time.time())}.json"
        try:
            json_path.write_text(
                json.dumps(metrics, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"INFO: Performance metrics written to JSON: {json_path}")
        except Exception as exc:
            print(f"WARNING: failed to write JSON metrics — {exc}", file=sys.stderr)

    if truth_errors:
        print("FAIL — startup probe did not provide valid Qt first-paint evidence")
        for error in truth_errors:
            print(f"  - {error}")
        raise SystemExit(1)

    if gate_ms > threshold:
        pct = ((gate_ms - threshold) / threshold) * 100
        print(
            f"FAIL — startup gate {gate_ms} ms exceeds "
            f"threshold {threshold} ms (+{pct:.1f}%)"
        )
        raise SystemExit(1)

    print(f"PASS — startup gate {gate_ms} ms <= {threshold} ms  [OK]")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
