# Windows 启动 A/B 诊断（非发布门禁）

本诊断仅比较同一台原生 Windows x64 主机上的启动阶段，不发布安装包、不改变现有发布工作流和阈值。A 为 `ca358f9f62e4d8912a72f64f4600de52d9746acb`，B 为曾通过安装启动门禁的 `b30a42eef585624a7d30cb792dce46f5f0548262`。

## 反转首次位置的短诊断

```powershell
# 新 runner：只构建历史 B，连续两次完整桌面启动均使用相同只读旁观
python scripts/dev/windows_startup_ab.py --output-dir "$env:TEMP\ih-ab-b-first" --baseline-first --native-qt
```

该短协议只构建 B 的 onedir（不重新安装 Inno，也不构建 A）。两次均使用官方 5000 ms 门槛和独立合成运行目录。第一份样本是**该 runner 本次诊断首次 Invoice Hub 桌面进程/窗口**，其他系统窗口、构建阶段和文件缓存未必为空。预估构建约 2–4 分钟，具体取决于依赖安装和机器。

两次采样均由 Qt 之外的旁观进程用 Win32 只读 API 以约 50 ms 间隔确认官方 checker 的目标 exe 子进程，记录累计 user/kernel CPU、I/O 读次数与字节、页错误、线程、可见窗口以及少数相关模块名。`*.native-trace.json` 仅含合成程序，事件附带观测时刻及当时计数器，日志摘要另保留每秒最后一条计数。进程创建时间与官方内部 launch stages 的起点并不相同，窗口可见也不是 Qt Paint/物理呈现证明；非空探针临时文件可能是失败或部分写入，不能替代最终 checker 证据。CPU 为进程总计，I/O 是逻辑进程 I/O 而非物理磁盘读，页错误包含软/硬错误。目标进程过短、权限或采样间隙可能造成缺项；可用计数、最大采样间隙、旁观工作时间和错误均明确记录。旁观缺失不改变官方 checker 的退出码/门槛。首样本前后另外只读查询 FontCache 服务状态/启动类型、当前系统功耗方案 GUID 和会话类型；不清缓存、启停服务或改变系统防护，不采集/上传全系统 ETL。可选 `--native-qt` 在两个冻结样本之后对 B 的锁环境运行三项源窗口对照。

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
- `<输出目录>/work/` 保存 Git archive 解包源目录、各自 venv/完整构建和安装日志。诊断工作流只上传小型 `evidence/`。早期双版本和历史优先运行的附件保留三天。

诊断工作流仅在 `diagnostics/windows-startup-ab-ca358f9` 分支 push 时运行，单台 `windows-latest`，无发布权限。原双版 A/B、历史优先和实装接口仍可本地使用。

## 三版本首启 ETW 测量

本轮在同一台 Windows 上增加 F，产品优化提交为 `8c94421d97c9ddc02127ed399b8d82c4d379e532`。A 与 B 仍为本文前述的精确候选和历史版。各自从 Git 归档及三份锁定依赖构建。标准 GitHub 托管作业只从诊断分支触发。

```powershell
$collector = Join-Path $env:TEMP 'ih-etw-collector'
dotnet build scripts/dev/windows_startup_etw/StartupEtw.csproj -c Release -o "$collector"
dotnet (Join-Path $collector 'StartupEtw.dll') --self-test
python scripts/dev/windows_startup_ab.py --output-dir "$env:TEMP\ih-startup-etw" --optimized-sha 8c94421d97c9ddc02127ed399b8d82c4d379e532 --etw-collector (Join-Path $collector 'StartupEtw.dll')
```

需要原生 Windows x64、原发行的 Python 3.11 和 .NET SDK/runtime 8.0 或支持该目标的后续 SDK。构建阶段从 NuGet 取得固定 Microsoft TraceEvent 3.2.8 的诊断依赖。新会话需要系统 ETW 权限。每次正式样本使用原 checker 和合成运行目录。顺序如下。

| 阶段 | 顺序 | 观察 |
|---|---|---|
| 便携初次与重复启动 | F F A B B A F | 同时采集 ETW 和窗口/进程计数 |
| 暖态便携对照 | B A F F A B | 原 checker，独立新进程，无旁观察 |
| 可选实装 | F F | 真实 Inno 独立安装，版本/哈希/卸载核对，首次带 ETW |

实装仅在一次性环境显式追加 `--mode both --disposable-runner`，并提供可用的 Inno Setup。系统与各版本自身文件缓存不能清空，先后顺序逐样本保存。首位 F 与紧接 F 分开解释，后续 A/B 的第一次出现仍受各自文件缓存影响。对 A/F 的暖态回归使用最后相邻反向配对。ETW 及 50 ms 观察线程本身可能影响性能，附加阶段与无旁观察的运行分列。计时、首 Paint 真假检查以及 5000/2000 ms 门槛沿用发行 checker。

ETW 使用一次性的唯一具名实时系统日志会话。Windows 内核调度事件包含全局线程切换等元数据，实时处理器丢弃无关事件，只留官方 checker 启动、Win32 旁观者确认完整 EXE 路径和 PID/创建时间、且线程生存期一致的 Invoice Hub 事件。不生成全系统 ETL，不启用网络、注册表、文件操作/文件名或内容采集。不会改变防护、系统字体或 CPU 采样间隔。关闭时仅停止自身会话。未能捕获进程开始/结束或双端身份不匹配时，仅报告不可用。

生成的 `*.etw.json` 包含目标线程的调度点、生存期、硬缺页及关键等待区间。用切出/切入计算离开 CPU 的时间，用实际 ReadyThread 事件区分已观察到的等待与就绪调度延迟。缺少 ReadyThread 时保留未知量。最长等待和硬缺页保留可映射的栈模块基名及模块内偏移，其余帧标为 unmapped，不收集绝对地址或进程命令行。没有硬缺页映射的文件名，无法用计数确认特定字体文件或唤醒方。记录事件丢失、采样截断、会话清理、窗口 TID、采样点 QPC 和窗口可见观测。将有效探针文件出现作为实际 Qt Paint 的观察上界，若文件过早消失则标明采集范围至目标进程退出。官方 checker 的返回码和证据保持独立。

本轮工作流保留目标进程的诊断证据 30 天，完整现场未用通用 WPR 系统录制。Linux 可验证 C# 编译、调度算法及 Python 流程，只有实际 Windows 结果能确认 ETW 提供者、硬缺页、原生等待栈和性能。
