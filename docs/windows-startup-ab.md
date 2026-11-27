# Windows 启动 A/B 诊断（非发布门禁）

本诊断仅比较同一台原生 Windows x64 主机上的启动阶段，不发布安装包、不改变现有发布工作流和阈值。A 为 `ca358f9f62e4d8912a72f64f4600de52d9746acb`，B 为曾通过安装启动门禁的 `b30a42eef585624a7d30cb792dce46f5f0548262`。

## 一键运行

需要 Windows x64、64 位 Python 3.11 和完整 Git 历史。构建时需要能按两版锁文件安装依赖，实装另需 Inno Setup 6。请使用尚不存在的短路径作为输出目录。

```powershell
# 个人电脑：默认只在新目录构建并测量两个便携 onedir，不安装软件
python scripts/dev/windows_startup_ab.py --output-dir "$env:TEMP\ih-ab-portable"

# 一次性空白 Windows VM / 标准 GitHub-hosted runner：便携与真正的 Inno 实装
python scripts/dev/windows_startup_ab.py --output-dir "$env:TEMP\ih-ab-full" --mode both --disposable-runner --native-qt
```

默认顺序为 **ABBA、BAAB**，每种模式各八个样本（共十六次正式启动）；可用 `--order ABBA` 或 `--order BAAB` 做较短的一轮。真实安装模式每个样本均重新安装、核对安装位置/版本/源文件 SHA-256、运行发行版的嵌入版本探针和正式启动检查器、再用该次安装的卸载器卸载；不会把复制目录称为安装。若发现已有 Invoice Hub Inno 注册或默认安装目录，将拒绝实装；若清理失败，将停止后续实装。不要在日常使用的 Windows 用户账户中使用 `--disposable-runner`。

曾有单次 Windows release audit 的 PyInstaller 构建约 1 分半、Inno 构建及安装验收约 2 分钟；此处有两套依赖/构建、多次安装/卸载，通常需要十几至数十分钟，网络和主机运行情况可能显著改变耗时。工作流预留 50 分钟。仅现成包采样不需要网络或构建依赖，通常几十秒至数分钟。

## 离线比较已有的可信程序

```powershell
python scripts/dev/windows_startup_ab.py --output-dir "$env:TEMP\ih-ab-offline" `
  --candidate-exe "C:\diagnostics\A\InvoiceHub.exe" `
  --baseline-exe "C:\diagnostics\B\InvoiceHub.exe" --mode portable
```

若明确指定两个已经安装的程序路径，可用 `--mode installed` 比较 2000 ms 门槛；此模式**不执行安装或卸载，也不证明实装过程**。没有独立精确源构建证据的程序以 `caller-supplied-exe` 标识，记录完整文件 SHA-256 和调用者声明的源版本，不将其误称为已验证的源提交。不能对带有旧版安装目录 `exports` 的程序执行此模式，以免触发历史导出迁移。

## 如何看结果

- 每次正式样本使用原始 `scripts/check_startup_time.py --output-json`，实测完整审核窗口第一次 Qt Paint，保持便携 **5000 ms**、安装 **2000 ms**。每次都是新进程、独立运行目录和工作目录，空白 SQLite/配置、合成 workbench 迁移标记和空凭据后端；不迁移个人 UI 设置、不打开真实发票。没有清理操作系统缓存，不能将新进程等同于冷启动系统。
- `<输出目录>/evidence/` 保留每个原始 checker 日志和 JSON、`samples.jsonl`、`summary.json`、主机/依赖锁及二进制身份（可比的中位数仅供诊断）。逐样本同时输出 `PERF_AB_SAMPLE` JSON 行，结束输出 `PERF_AB_SUMMARY`。超门槛不跳过后续正常样本，最终退出非零；安装/清理异常中止后续实装并标出证据不完整。
- `--native-qt` 仅在全部正式冻结样本之后运行，两版源码环境各三个新进程：直接生产闪屏、先空窗口再生产闪屏、先 Segoe UI 中英文普通标签再生产闪屏。前置窗口沿用生产闪屏的窗口类型和透明属性，只改变其内容；记录各阶段 wall/CPU 时间、Qt 版本及屏幕尺寸/DPR。这是 `PERF_AB_QT` 辅助对照，不计入正式首次 Paint 门槛。
- `<输出目录>/work/` 保存两套 Git archive 解包源目录、各自 venv/完整构建和安装日志。诊断工作流只上传小型 `evidence/`，保留三天，不上传程序、venv 或运行数据库。

诊断工作流仅在 `diagnostics/windows-startup-ab-ca358f9` 分支 push 时运行，单台 `windows-latest`，无发布权限；本地也可直接运行相同入口。在 Windows 实测之前，Linux 只能验证脚本语法、调度与证据处理逻辑，不能据此宣称 Windows 性能通过。
