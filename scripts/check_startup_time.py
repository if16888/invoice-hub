#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/check_startup_time.py — Invoice Hub 启动性能门槛校验器。

优先读取 probe JSON，fallback 到 stdout，同时测量外部进程 wall time。

使用方式：
    # 验证打包后的 PyInstaller 可执行文件：
    python scripts/check_startup_time.py dist/InvoiceHub/InvoiceHub.exe

    # 在开发模式下直接运行 Python 模块验证：
    python scripts/check_startup_time.py --python

    # 自定义超时门槛（毫秒）：
    python scripts/check_startup_time.py dist/InvoiceHub/InvoiceHub.exe --threshold 3000

退出码：
    0  — 启动时间在允许的阈值内
    1  — 启动时间超过设定阈值，或程序找不到/运行超时
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

# ── Default thresholds ────────────────────────────────────────────────
LOCAL_THRESHOLD_MS = 2000    # strict target for local builds
CI_THRESHOLD_MS = 3000       # relaxed threshold for GitHub Actions runners

# ── Patterns ──────────────────────────────────────────────────────────
_RE_STARTUP_MS = re.compile(r"^STARTUP_MS=(\d+)", re.MULTILINE)
_RE_APP_INIT_MS = re.compile(r"^APP_INIT_MS=(\d+)", re.MULTILINE)
_RE_SHOW_MS = re.compile(r"^MAIN_WINDOW_SHOW_MS=(\d+)", re.MULTILINE)

PROBE_TIMEOUT_S = 30  # bail out if probe takes longer than this


def _build_cmd(exe_path: Path | None, python_mode: bool) -> list[str]:
    if python_mode:
        return [
            sys.executable, "-m", "scripts.invoice_fetch",
            "desktop", "--startup-probe",
        ]
    if exe_path is None:
        print("ERROR: must supply an EXE path or use --python", file=sys.stderr)
        sys.exit(1)
    return [str(exe_path), "desktop", "--startup-probe"]


import os
import json
import tempfile

_RE_DB_OPEN_MS = re.compile(r"^DB_OPEN_MS=(\d+)", re.MULTILINE)


def run_probe(cmd: list[str]) -> dict[str, int]:
    """Run the startup probe and return the parsed metric dict."""
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
            timeout=PROBE_TIMEOUT_S,
            creationflags=0,
            env=custom_env,
        )
    except subprocess.TimeoutExpired:
        print(
            f"ERROR: probe timed out after {PROBE_TIMEOUT_S}s "
            "(startup took too long or probe mode not supported)",
            file=sys.stderr,
        )
        temp_path.unlink(missing_ok=True)
        sys.exit(1)
    except FileNotFoundError as exc:
        print(f"ERROR: executable not found — {exc}", file=sys.stderr)
        temp_path.unlink(missing_ok=True)
        sys.exit(1)

    process_wall_ms = int((time.perf_counter() - t_start) * 1000)

    metrics = {
        "APP_INIT_MS": -1,
        "DB_OPEN_MS": -1,
        "MAIN_WINDOW_SHOW_MS": -1,
        "STARTUP_MS": -1,
        "GUI_INIT_MS": -1,
        "FIRST_LOAD_MS": -1,
        "FIRST_PAINT_MS": -1,
        "TOTAL_STARTUP_MS": -1,
        "PROCESS_WALL_MS": process_wall_ms,
    }

    # 1. Prioritize reading from the JSON probe file
    if temp_path.exists() and temp_path.stat().st_size > 0:
        try:
            with open(temp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in metrics:
                    if k in data:
                        metrics[k] = data[k]
                print("Parsed metrics successfully from probe JSON file.")
        except Exception as exc:
            print(f"WARNING: failed to parse probe JSON file — {exc}", file=sys.stderr)

    temp_path.unlink(missing_ok=True)

    # 2. Fallback to stdout parsing
    combined = result.stdout + result.stderr

    def _parse(pattern: re.Pattern, label: str, default_val: int) -> int:
        if default_val >= 0:
            return default_val
        m = pattern.search(combined)
        if m:
            return int(m.group(1))
        return -1

    metrics["APP_INIT_MS"] = _parse(_RE_APP_INIT_MS, "APP_INIT_MS", metrics["APP_INIT_MS"])
    metrics["DB_OPEN_MS"] = _parse(_RE_DB_OPEN_MS, "DB_OPEN_MS", metrics["DB_OPEN_MS"])
    metrics["MAIN_WINDOW_SHOW_MS"] = _parse(_RE_SHOW_MS, "MAIN_WINDOW_SHOW_MS", metrics["MAIN_WINDOW_SHOW_MS"])
    metrics["STARTUP_MS"] = _parse(_RE_STARTUP_MS, "STARTUP_MS", metrics["STARTUP_MS"])
    metrics["GUI_INIT_MS"] = _parse(re.compile(r"^GUI_INIT_MS=(\d+)", re.MULTILINE), "GUI_INIT_MS", metrics["GUI_INIT_MS"])
    metrics["FIRST_LOAD_MS"] = _parse(re.compile(r"^FIRST_LOAD_MS=(\d+)", re.MULTILINE), "FIRST_LOAD_MS", metrics["FIRST_LOAD_MS"])
    metrics["FIRST_PAINT_MS"] = _parse(re.compile(r"^FIRST_PAINT_MS=(\d+)", re.MULTILINE), "FIRST_PAINT_MS", metrics["FIRST_PAINT_MS"])
    metrics["TOTAL_STARTUP_MS"] = _parse(re.compile(r"^TOTAL_STARTUP_MS=(\d+)", re.MULTILINE), "TOTAL_STARTUP_MS", metrics["TOTAL_STARTUP_MS"])

    if metrics["STARTUP_MS"] < 0:
        print("Probe stdout:", result.stdout[:500], file=sys.stderr)
        print("Probe stderr:", result.stderr[:500], file=sys.stderr)

    return metrics


def main():
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

    exe_path = Path(args.exe) if args.exe else None
    if exe_path and not exe_path.exists():
        print(f"ERROR: EXE not found: {exe_path}", file=sys.stderr)
        sys.exit(1)

    cmd = _build_cmd(exe_path, args.python)
    metrics = run_probe(cmd)
    startup_ms = metrics["STARTUP_MS"]
    process_wall_ms = metrics["PROCESS_WALL_MS"]
    effective_ms = max(process_wall_ms, startup_ms)

    # Output detailed performance table in Chinese
    print()
    print("+----------------------------------------------------------------+")
    print("|         Invoice Hub 桌面端启动耗时性能指标报告         |")
    print("+--------------------------------------+-------------------------+")
    print("| 阶段名称                             | 耗时 (毫秒)             |")
    print("+--------------------------------------+-------------------------+")
    print(f"| APP_INIT_MS (应用底层依赖/模块载入)  | {metrics['APP_INIT_MS']:<23} |")
    print(f"| DB_OPEN_MS (SQLite数据库加载与迁移)  | {metrics['DB_OPEN_MS']:<23} |")
    print(f"| GUI_INIT_MS (GUI框架及主布局初始化)  | {metrics['GUI_INIT_MS']:<23} |")
    print(f"| FIRST_LOAD_MS (首屏发票与报销组载入) | {metrics['FIRST_LOAD_MS']:<23} |")
    print(f"| MAIN_WINDOW_SHOW_MS (首帧渲染展现)   | {metrics['MAIN_WINDOW_SHOW_MS']:<23} |")
    print(f"| FIRST_PAINT_MS (物理渲染完成)        | {metrics['FIRST_PAINT_MS']:<23} |")
    print(f"| STARTUP_MS (内部逻辑计算总时长)      | {startup_ms:<23} |")
    print(f"| TOTAL_STARTUP_MS (应用实际冷启动)    | {metrics['TOTAL_STARTUP_MS']:<23} |")
    print(f"| PROCESS_WALL_MS (外部实测物理总用时) | {process_wall_ms:<23} |")
    print("+--------------------------------------+-------------------------+")
    print(f"| 判定冷启动参考耗时 (Effective Ms)    | {effective_ms:<23} |")
    print(f"| 超时判定门槛 (Threshold Limit)       | {threshold:<23} |")
    print("+----------------------------------------------------------------+")
    print()

    # Output to JSON
    if args.output_json:
        bench_dir = Path("bench-local/results")
        bench_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        json_path = bench_dir / f"startup_metrics_{timestamp}.json"
        try:
            with open(json_path, "w", encoding="utf-8") as jf:
                json.dump(metrics, jf, indent=2, ensure_ascii=False)
            print(f"INFO: Performance metrics written to JSON: {json_path}")
        except Exception as e:
            print(f"WARNING: failed to write JSON metrics — {e}", file=sys.stderr)

    if startup_ms < 0:
        print("FAIL — could not parse STARTUP_MS from probe output")
        sys.exit(1)

    if effective_ms > threshold:
        pct = ((effective_ms - threshold) / threshold) * 100
        print(f"FAIL — effective startup time {effective_ms} ms exceeds threshold {threshold} ms (+{pct:.1f}%)")
        sys.exit(1)

    print(f"PASS — effective startup time {effective_ms} ms <= {threshold} ms  [OK]")
    sys.exit(0)


if __name__ == "__main__":
    main()
