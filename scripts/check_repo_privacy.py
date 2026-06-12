#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Invoice Hub Repository Privacy Hygiene Checker
Scans staged and tracked files for high-risk financial data identifiers and forbidden file formats.
"""

import os
import sys
import subprocess
from pathlib import Path

# High-risk financial data keywords
HIGH_RISK_KEYWORDS = [
    "纳税人识别号",
    "统一社会信用代码",
    "发票号码",
    "开户行及账号",
    "银行账号",
    "开票人",
    "价税合计",
]

# File formats that should never be committed/tracked
FORBIDDEN_EXTENSIONS = [
    ".pdf",
    ".ofd",
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".xlsx",
    ".zip",
]

# Directory prefixes that should never contain tracked or staged files
FORBIDDEN_DIR_PREFIXES = [
    ".claude/",
    "scratch/",
    "runtime/",
    "exports/",
    "private-data/",
    "real-samples/",
    "downloads/",
    "attachments/",
]

ALLOWED_BINARY_PREFIXES = [
    "docs/images/",
    "scripts/invoice_fetch/gui/assets/",
    "tests/fixtures/synthetic/",
]

def run_cmd(args, cwd=None):
    """Run a shell command and return its output lines."""
    try:
        res = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=cwd,
            check=True
        )
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except (subprocess.SubprocessError, FileNotFoundError):
        return []

def should_skip_keyword_check(file_path):
    """Determine if a file path can skip keyword check."""
    posix_path = Path(file_path).as_posix()

    # 1. Skip check script itself
    if file_path == "scripts/check_repo_privacy.py":
        return True

    # 2. Skip synthetic test fixtures
    if "tests/fixtures/synthetic" in posix_path:
        return True

    # 3. Skip .py code files (containing parsing logic, assertions, regexes)
    if Path(file_path).suffix.lower() == ".py":
        return True

    # 4. Skip repository documentation which explains the rules and keywords
    if file_path in ["README.md", "AGENTS.md"] or posix_path.startswith("docs/"):
        return True

    return False

def check_file_leak(file_path):
    """Scan a file for forbidden directories, forbidden extensions, or high-risk keywords."""
    path = Path(file_path)
    posix_path = path.as_posix()

    # 1. Check forbidden directory prefixes
    if "tests/fixtures/synthetic" not in posix_path:
        for prefix in FORBIDDEN_DIR_PREFIXES:
            if posix_path.startswith(prefix) or f"/{prefix}" in posix_path:
                print(f"[错误] 禁用的目录内文件已被跟踪/暂存: '{file_path}'")
                return False

    # 2. Check forbidden extensions
    if path.suffix.lower() in FORBIDDEN_EXTENSIONS:
        # Whitelist synthetic documentation images, synthetic fixtures, and standard GUI assets.
        if not any(posix_path.startswith(prefix) for prefix in ALLOWED_BINARY_PREFIXES):
            print(f"[错误] 禁用的文件格式已被跟踪/暂存: '{file_path}'")
            return False

    # 3. Check keywords unless specifically whitelisted or code files
    if should_skip_keyword_check(file_path):
        return True

    # Scan file contents for keywords
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            for kw in HIGH_RISK_KEYWORDS:
                if kw in content:
                    print(f"[错误] 发现高风险敏感词汇 '{kw}' 泄漏在文件: '{file_path}'")
                    return False
    except Exception as e:
        # If we cannot read it as text, flag it as warning if not a known binary asset
        print(f"[警告] 无法读取文件以进行隐私扫描: '{file_path}' ({e})")

    return True

def main():
    print("[隐私审查] 启动本地仓库隐私与合规性扫描...")

    repo_root = Path(__file__).resolve().parent.parent

    # Get staged files
    staged_files = run_cmd(["git", "diff", "--cached", "--name-only"], cwd=str(repo_root))

    # Get tracked files
    tracked_files = run_cmd(["git", "ls-files"], cwd=str(repo_root))

    # Combine unique files
    files_to_check = sorted(list(set(staged_files + tracked_files)))

    has_leak = False
    checked_count = 0

    for f in files_to_check:
        full_path = repo_root / f
        if not full_path.exists():
            continue

        checked_count += 1
        if not check_file_leak(f):
            has_leak = True

    print(f"[扫描统计] 扫描完成。共检查 {checked_count} 个暂存/跟踪文件。")

    if has_leak:
        print("[扫描结果: 失败] 仓库中存在敏感财务数据泄漏或禁用的文件格式！发布已被阻断。")
        sys.exit(1)
    else:
        print("[扫描结果: 通过] 未检测到任何高风险词汇泄露，文件格式全部合规。")
        sys.exit(0)

if __name__ == "__main__":
    main()
