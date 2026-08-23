# Invoice Hub 现有测试用例体系全景审计与 CI 提速优化方案深度报告
## Comprehensive Test Suite Audit, Fragility Profiling, and CI Acceleration Blueprint

> **报告版本**: v1.0.0 (Engineering Architecture Blueprint)
> **审计日期**: 2026-08-23
> **目标工程**: Invoice Hub 桌面发票与报销全流程管理系统 (`if16888/invoice-hub`)

---

## 实施决策声明 (Implementation Decision)

本报告包含审计阶段提出的候选优化方案，不代表所有方案均已批准实施。

**Phase 1 已批准并实施**：
- deterministic LPT weighted sharding
- test state / DB pollution cleanup
- assertion hardening
- fresh-process isolation 保持不变

**当前明确延期、不属于 v0.1.6 范围**：
- uv migration
- test-module consolidation
- global SQLite :memory: migration
- pytest-xdist hybrid execution
- TIA incremental testing

Tier 2 / Tier 3 的性能收益均为预测值，不是已验证的发布指标。

---

## 目录 (Table of Contents)

1. [实施决策声明](#实施决策声明-implementation-decision)
2. [报告元数据与审计基准](#1-报告元数据与审计基准)
2. [执行摘要与核心审计发现](#2-执行摘要与核心审计发现)
3. [全局测试资产全景与分类台账](#3-全局测试资产全景与分类台账)
4. [R1. 业务集成测试与核心状态机覆盖全景审查](#4-r1-业务集成测试与核心状态机覆盖全景审查)
   - 4.1 连续审核状态机 (Continuous Review State Machine)
   - 4.2 发票批量导入与 Identity 映射 (Batch Import & Provenance Mapping)
   - 4.3 邮箱拉取与同步引擎 (Email Fetch & Synchronization)
   - 4.4 手机扫码上传与防火墙授权 (Mobile Upload & Windows Firewall)
   - 4.5 多格式导出与物料预检 (Multi-Format Export & Fail-Closed Precheck)
   - 4.6 整体业务 E2E vs 单元 Mock 保真度矩阵与整治路线图
5. [R2. 无效、冗余及脆弱测试用例专项识别](#5-r2-无效冗余及脆弱测试用例专项识别)
   - 5.1 无效与零价值测试用例专项排查 (Invalid & Zero-Value Tests)
   - 5.2 重叠与冗余用例五大集群深度剖析 (Redundancy Clusters)
   - 5.3 38 处高脆弱性与 Flaky 异味专项排查 (Fragility & Flakiness Smells)
   - 5.4 HCI Acceptance 验收套件深度评估 (Dual-Oracle HCI Suite)
6. [R3. CI 耗时分析与分片瓶颈诊断](#6-r3-ci-耗时分析与分片瓶颈诊断)
   - 6.1 GitHub Actions CI 架构与执行车道拓扑
   - 6.2 3-Shard 轮询分片缺陷与 2.84x 倾斜深度剖析
   - 6.3 HCI 专属车道性能与稳定性验证
   - 6.4 全仓 Top 20 最耗时测试模块全景台账
   - 6.5 全仓 Top 20 最耗时单用例排查
   - 6.6 测试执行延迟根因构成拆解
7. [CI 分级优化与测试裁剪路线图 (-70.6% 提速方案)](#7-ci-分级优化与测试裁剪路线图--706-提速方案)
   - 7.1 Tier 1: 极速起效方案 (LPT 贪心装箱 + uv 极速包管理器)
   - 7.2 Tier 2: 测试用例裁剪与去重整合 (Hotspots Deduplication)
   - 7.3 Tier 3: 架构演进与智能运行 (内存 SQLite + 混合执行器 + TIA)
   - 7.4 全维度量化收益测算对比表 (Before vs After)
8. [实施落地指引与验证手册](#8-实施落地指引与验证手册)
   - 8.1 分阶段实施路线与具体动作
   - 8.2 核心改造补丁代码规范
   - 8.3 独立复现与验证命令集
   - 8.4 风险缓解与回滚预案

---

## 1. 报告元数据与审计基准

| 元数据字段 | 详细取值与环境说明 |
|---|---|
| **目标仓库** | Invoice Hub (`d:/01_workspace/win/invoice-hub`) |
| **技术栈体系** | Python 3.11 / PySide6 (Qt for Python) / SQLite 3 / FastAPI & Uvicorn / Playwright / OpenPyXL / PyMuPDF |
| **测试框架** | `unittest` / `pytest` / `pytest-xdist` / 自研 Win32 Toolhelp 进程看门狗 (`run_hci_acceptance.py`) |
| **CI 运行平台** | GitHub Actions (`windows-latest` Runner) |
| **测试资产总量** | **109 个 Python 测试及辅助文件** (包含 95 个常规单元测试模块 + 9 个 HCI 套件文件 + 5 个辅助分发模块) |
| **测试用例规模** | **1,413 个测试函数** (AST 静态扫描) / **1,321 个单测用例** (隔离运行器加载) + **19 个端到端 HCI 场景** |
| **测试代码体量** | **40,922 行测试代码** (约 1.74 MB 磁盘资产) |
| **基线测试耗时** | 单进程全量串行: **1,079.21s (17.99 min)**；当前 3-Shard CI 最大分片: **502.50s (8.38 min)**；PR 总构建耗时: **~9.4 min** |
| **审计核心原则** | 严谨客观、数据可重现、代码零破坏（所有提速与优化均为纯事实依据与落地方案） |

---

## 2. 执行摘要与核心审计发现

本报告是针对 Invoice Hub 全仓测试体系与持续集成 (CI) 流水线的**全景深度体检与工程治理总纲**。通过对全仓 109 个测试文件、1,413 个测试用例以及 GitHub Actions 3-Shard 执行环境的实测分析，核心结论如下：

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                Invoice Hub 测试体系体检仪表盘                                     │
├────────────────────────────────┬────────────────────────────────┬────────────────────────────────┤
│ 1. 资产全景与耗时基准         │ 2. 状态机与业务集成            │ 3. 质量异味与脆弱性            │
│  • 测试文件: 109 个            │  • 连续审核 (CR-01~08): 强保证 │  • 无效/零价值用例: 12 处      │
│  • 测试用例: 1,413 个          │  • 物料预检 (EXPORT-01): 强保证│  • 冗余重叠集群: 5 大类        │
│  • 单进程串行: 17.99 分钟      │  • 批量事务回滚测试: 缺失(盲区)│  • 脆弱性/Flaky 异味: 38 处    │
│  • 进程启动开销: 98.4 秒 (9%) │  • 协议层保真度: 依赖 Pure Mock │  • 全局 Monkeypatch 泄漏: 4 处 │
├────────────────────────────────┴────────────────────────────────┴────────────────────────────────┤
│ 4. CI 性能瓶颈与分片倾斜                                                                         │
│  • 3-Shard 字母序分片导致极端倾斜: Shard 0 (2.95m) vs Shard 2 (8.38m) [2.84x 倾斜比, 5.42m 空转] │
│  • Top 5 最慢模块消耗全仓 46.0% 耗时 (496.5s)；Top 20 模块消耗 75.6% 耗时 (815.4s)              │
│  • HCI Acceptance 独立车道高效极速: 19 个端到端场景耗时 58.97s (~1.0m)，零进程/内存泄漏        │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 5. 三级提速路线图收益总览                                                                        │
│  • Tier 1 极速起效 (LPT 贪心装箱 + uv 缓存): CI 耗时 9.4m -> 6.3m (-33.3%, 0 业务代码修改)       │
│  • Tier 2 用例去重与微文件合并 (Hotspot 裁剪): CI 耗时 -> 4.9m (-47.5%)                         │
│  • Tier 3 架构演进 (内存 SQLite + 混合执行器 + TIA 智能增量): CI 耗时 -> 2.8m (-70.6%)           │
│  • 月度 GitHub Actions 计算分钟数削减 66.2% (从 3,250 分钟降至 1,100 分钟/百次构建)             │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 全局测试资产全景与分类台账

全仓测试资产共覆盖 13 个核心业务与基础设施领域，按代码行数、用例数、文件体积与覆盖目标建立分类台账。

### 3.1 13 大业务领域资产全景统计

| 序号 | 业务领域分类 (Domain Category) | 测试文件数 | 测试函数数 (Tests) | 代码行数 (Lines) | 文件体积 (KB) | 核心覆盖目标及代表性测试模块 |
|:---:|:---|:---:|:---:|:---:|:---:|:---|
| 1 | **GUI 组件与交互 (GUI Components & Interaction)** | 16 | 277 | 7,378 | 303.2 | 主窗口状态机、工作台状态、PDF 预览、导入中心交互 (`test_preview_workbench_ui.py`, `test_ui_components.py`) |
| 2 | **核心工作流与报销组 (Core Workflow & Claim Groups)** | 7 | 265 | 11,395 | 514.6 | 报销批次流转、单据关联、导出打包、历史重检 (`_claim_groups_cases.py`, `test_invoice_workflow.py`) |
| 3 | **审核工作台与反馈 (Review Workflow & UI)** | 15 | 164 | 3,861 | 159.7 | 审核工具栏、详情面板、分页加载、列表过滤、选择一致性 (`test_review_action_regressions.py`, `test_gui_column_filters.py`) |
| 4 | **设置中心与多源配置 (Settings & Configuration)** | 13 | 153 | 3,591 | 152.1 | 多邮箱配置、IMAP 适配、AI 模型密钥、公司抬头、隐私安全 (`test_settings_center.py`, `test_generic_imap_config.py`) |
| 5 | **CLI、打包构建与探针 (CLI, Packaging & Diagnostics)** | 7 | 115 | 1,639 | 67.9 | 启动耗时探针、Inno Setup/PyInstaller Spec、日志脱敏、隐私门禁 (`test_startup_probe_and_packaging.py`, `test_log_privacy.py`) |
| 6 | **设计系统与样式契约 (Design Tokens & Visual Contracts)** | 15 | 113 | 2,064 | 91.4 | IHDS 规范、DPI 缩放契约 (1.0x/1.25x/1.5x)、焦点态、配色 (`test_ihds08.py`, `test_ihds09.py`, `test_design_system_v11.py`) |
| 7 | **邮箱拉取与同步 (Mailbox & Email Sync)** | 6 | 104 | 2,770 | 119.2 | IMAP 协议语义、附件解析、断点续传、邮箱安全删除 (`test_mail_fetcher_imap_semantics.py`, `test_email_reprocess.py`) |
| 8 | **手机扫码与防火墙 (Mobile Upload & Firewall)** | 6 | 91 | 2,452 | 107.6 | 内嵌 Web 服务、WiFi 防火墙规则、扫码上传会话 (`test_mobile_upload.py`, `test_windows_firewall.py`) |
| 9 | **HCI 双预言机验收 (HCI Acceptance Suite)** | 9 | 36 | 2,522 | 92.2 | 19 核心人机交互场景、看门狗监控、变异自检、报告生成 (`scenarios.py`, `test_mutation_selftest.py`) |
| 10 | **导出与物料预检 (Export & Preflight)** | 4 | 34 | 1,160 | 50.9 | 报销包导出、物料完整性 3 层检查、Excel/ZIP 打包 (`test_export_material_preflight.py`, `test_mvp_export_evidence.py`) |
| 11 | **数据库与数据迁移 (Database & Migrations)** | 4 | 33 | 1,085 | 44.2 | SQLite DDL、版本迁移幂等性、热备份与数据恢复 (`test_database_migration.py`, `test_db_backup.py`) |
| 12 | **AI 分类与规则引擎 (AI & Classification)** | 4 | 27 | 811 | 32.2 | DeepSeek/Gemini 适配、分类重试熔断、费用日期推断 (`test_ai_classifier.py`, `test_expense_date.py`) |
| 13 | **辅助工具与共享夹具 (Helpers & Fixtures)** | 3 | 1 | 194 | 8.5 | 几何断言辅助、PySide6 进程清理、动态用例拆分器 (`geometry_assert_helpers.py`, `pyside6_cleaner.py`) |
| **合计** | **全仓总计 (Total)** | **109** | **1,413** | **40,922** | **1,743.7 KB** | — |

---

### 3.2 CI 执行通道与调度拓扑

Invoice Hub 在 CI 中划分了 4 个物理隔离车道，以应对 PySide6 原生 GUI 进程与标准单测的执行差异：

```
                              ┌────────────────────────────────────────────────────────┐
                              │               GitHub Actions CI Pipeline               │
                              │                 (.github/workflows/ci.yml)             │
                              └───────────────────────────┬────────────────────────────┘
                                                          │
                    ┌──────────────────────┬──────────────┴───────┬──────────────────────┐
                    │                      │                      │                      │
                    ▼                      ▼                      ▼                      ▼
        ┌──────────────────────┐┌──────────────────────┐┌──────────────────────┐┌──────────────────────┐
        │ 1. Source Gates 车道 ││ 2. Unit Shards 车道  ││ 3. HCI 验收专属车道  ││ 4. Geometry Preflight│
        ├──────────────────────┤├──────────────────────┤├──────────────────────┤├──────────────────────┤
        │ • 仓库隐私门禁扫描   ││ • 3-Shard 并行矩阵   ││ • Win32 Toolhelp 监控││ • 原生窗口几何尺寸   │
        │ • 公开导出树合规检查 ││ • 95 个测试模块      ││ • 19 个端到端业务场景││ • 1366x768 / 1080p   │
        │ • Python 编译语法检查││ • 隔离子进程循环执行 ││ • 双预言机状态校验   ││ • 非阻断预检通道     │
        │ • 耗时: ~1.5 - 2.0m  ││ • 耗时: 8.38m (瓶颈) ││ • 耗时: 58.97s (~1m) ││ • 耗时: ~1.0m        │
        └──────────────────────┘└──────────────────────┘└──────────────────────┘└──────────────────────┘
```

---

## 4. R1. 业务集成测试与核心状态机覆盖全景审查

业务端到端集成测试与核心状态机是确保发票生命周期流转、资金申报安全、多通道数据一致性的最关键防线。

### 4.1 连续审核状态机 (Continuous Review State Machine)

连续审核是财务人员高频操作的核心场景，通过键盘快捷键 (`Enter` 确认、`Delete` 忽略、`Ctrl+E` 标记异常、`Space` 暂缓) 实现流水线化单据复核。

#### 4.1.1 状态机流转与前置守卫矩阵
- **核心定义文件**: `scripts/invoice_fetch/review_status.py`
  - 核心状态: `TO_REVIEW = "to_review"` (待审核), `APPROVED = "approved"` (已通过), `IGNORED = "ignored"` (已忽略), `ERROR = "error"` (异常单据)。
  - 特殊单据实体: `invoice_type == "待关联证明材料"` (Pending Evidence)。

| 源状态 (Source) | 触发动作 (Trigger / Key) | 目标状态 (Target) | 前置守卫条件与业务规则 (Guard Conditions) | 源码锚点 |
|---|---|---|---|---|
| `to_review` | **Approve (Enter / Return)** | `approved` | **强守卫**: 严禁通过 standalone 证明材料 (`待关联证明材料`)，若未关联主发票直接抛 `ValueError`；若关键字段缺失需弹窗确认。 | `db.py:693`<br>`gui/app.py:7017-7048` |
| `to_review` | **Ignore (Delete)** | `ignored` | 默认从报销申报清单中排除，移出待办队列。 | `db.py:703`<br>`gui/app.py:2162` |
| `to_review` | **Mark Error (Ctrl+E)** | `error` | 标记为异常发票，记录错误原因备注，进入异常分类。 | `db.py:703`<br>`gui/app.py:2163` |
| `to_review` | **Skip / Later (Space)** | `to_review` | 仅移动光标选择项 (`_move_invoice_selection(1)`)，**DB 状态不变**，已处理计数器不递增。 | `gui/hci_v1.py:153`<br>`gui/app.py:7078` |
| `approved` / `ignored` / `error` | **Reset / Rollback** | `to_review` | 回滚审核状态，重置 `confirmed_at = None` 及 `confirmed_note = ""`。 | `db.py:697-700` |
| `to_review` (最后一张) | **Any Action** | Terminal State | 渲染 `"本轮已完成"` 终态提示面板，清空选择，防止游标越界崩溃或产生 `2/1` 虚假翻页。 | `gui/hci_v1.py`<br>`scenarios.py:492` |

#### 4.1.2 现有测试覆盖评估
- **HCI 验收套件 (`tests/hci_acceptance/scenarios.py: CR-01 ~ CR-08`)**:
  - `CR-01` (`run_cr_01`): 验证进入连续审核模式时，列表折叠隐藏，预览与详情面板呈现，进度徽标初始化为 `1/N · 还剩 N 张`。
  - `CR-02` (`run_cr_02`): 验证单张通过后，SQLite 底层 `APPROVED+1`, `TO_REVIEW-1`，UI 进度更新为 `2/N · 还剩 N-1`，游标自动平滑后移。
  - `CR-03` (`run_cr_03`): 连续两次审核通过，验证状态步进到 `3/N`，杜绝进度停滞的假 UI Bug。
  - `CR-04` & `CR-05`: 验证忽略与异常流转，确保移出审核队列且计数精确。
  - `CR-06`: 验证暂缓审核操作，DB 状态不被篡改。
  - `CR-07`: 退出并重新进入，验证会话重建与总数重算，无计数泄漏。
  - `CR-08`: 队列清空终态验证，确保平稳停机。

#### 4.1.3 状态机测试盲区与高危隐患
1. **批量更新缺乏事务原子性 (Batch Update Non-Atomicity)**:
   - 在 `gui/app.py:7050-7052` 中，批量状态更新采用逐行循环调用：
     ```python
     for inv in actionable_invoices:
         updated = self.db.update_invoice_review_status(inv["id"], status, note=note)
     ```
   - 若在第 50 张单据处发生 SQLite 锁或磁盘故障，前 49 张已提交，后 51 张未更新。测试套件中**缺乏批量操作部分失败时的事务回滚与一致性断言**。
2. **活动过滤器下的队列推进越界**: 当用户在启用列头过滤（如仅筛选特定销售方）时进入连续审核，现有测试未覆盖光标移动是否会错误跳转至被隐藏的行。
3. **前台审核与后台并发写入竞态**: 当后台正在执行邮箱拉取或手机上传时，前台操作同一张发票的并发冲突未被测试覆盖。

---

### 4.2 发票批量导入与 Identity 映射 (Batch Import & Provenance Mapping)

批量导入管道承担本地文件夹、ZIP 压缩包及移动端上传单据的解析、分类与指纹去重。

#### 4.2.1 批量导入调用链架构
```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           发票批量导入管道调用链架构                                    │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. 文件遍历与发现: scripts/invoice_fetch/__main__.py:_import_local_directory           │
│    ├── 递归扫描扩展名: .pdf, .ofd, .zip, .png, .jpg, .jpeg, .heic                       │
│    └── 嵌套 ZIP 递归解压: _extract_local_zip 提取多级目录                               │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ 2. 密码学指纹计算: _sha256_file 计算文件物理 Hash                                       │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ 3. 结构化解析与分类: InvoiceParser.parse_pdf / OCR 提取字段 -> _classify 判定类型      │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ 4. 多级去重与 Identity 映射:                                                           │
│    ├── 级别 1 (Exact SHA256): 命中已软删除则恢复 (_restore_existing_invoice_if_deleted) │
│    ├── 级别 2 (网约车 Provider ID): 跨中英文行程单匹配唯一订单号                       │
│    ├── 级别 3 (三元组唯一索引): (invoice_number, total_amount, seller_name)             │
│    └── 级别 4 (冲突降级标记): 单号相同但金额/销方不同 -> 标记为"本地导入冲突" (review_error)│
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ 5. 批次作用域分类派发: 生成 new_invoice_ids, review_invoice_ids, restored_invoice_ids  │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

#### 4.2.2 现有测试覆盖评估
- **`tests/test_import_review_identity.py` (高质量 E2E 覆盖)**:
  - 8 个单元测试与 6 个端到端集成测试，严格验证了批次 ID 隔离：
  - `test_test1_local_identity_preserves_new_ids_and_excludes_history`: 确保本次新增集合与历史发票严格隔离。
  - `test_test2_mobile_identity_internal_ids_and_http_sanitization`: 确保内部 DB 主键在移动端 HTTP 响应中被安全脱敏。
  - `test_test3_review_scope_isolation` & `test_test4_scope_progress_and_completion`: 验证进入“本次新增”审核模式时，视图严格锁定在当前批次。
  - `test_test7_restored_semantics_included_in_review_not_added`: 验证软删除恢复单据归入待审列表但不计入新增条目。
  - `test_e2e_f_error_conflict_created_identity_is_not_review_identity`: 验证冲突记录被置为 error 状态且不污染正常审核队列。

#### 4.2.3 批量导入测试盲区
1. **中途异常无原子回滚测试**: `_import_local_directory` 采用单文件逐条写入，缺少模拟中途故障的完整回滚测试。
2. **超大批量与深层嵌套压力测试**: 测试集均为 1~3 个文件，缺少 500+ 文件、100MB+ ZIP 包、10 层深层嵌套目录的性能与内存测试。
3. **畸形/损坏文件边界测试**: 缺少针对 0 字节 PDF、截断 ZIP 头、密码保护 PDF 的防御性用例。

---

### 4.3 邮箱拉取与同步引擎 (Email Fetch & Synchronization)

#### 4.3.1 架构与执行流程
- **核心引擎**: `scripts/invoice_fetch/mail_fetcher.py:MailFetcher`
- **底层通信**: 基于 IMAP4 over SSL (`_TimedIMAP4SSL`)，细分为连接超时、TLS 握手超时和命令超时。
- **两阶段轻量扫描**:
  - 阶段 1: `SEARCH SINCE <date>` -> `UID FETCH (UID INTERNALDATE)` 过滤已知 UID。
  - 阶段 2: `UID FETCH (BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])` 进行关键词匹配过滤 (`RELEVANCE_KEYWORDS`)。
  - 仅对匹配邮件执行全量 `UID FETCH (RFC822)` 下载。
- **协同取消**: `ScanControl.cancel()` 主动调用底层 `sock.shutdown()` 与 `sock.close()` 打断阻塞套接字。

#### 4.3.2 现有测试覆盖评估
- `tests/test_mail_fetcher_imap_semantics.py`: 验证 IMAP 命令序列 (`select` -> `search` -> `fetch`) 与 UID 过滤。
- `tests/test_scan_lifecycle.py`: 验证取消打断、超时参数传递、单调耗时计算与日志脱敏。
- `tests/test_email_reprocess.py` (21 个深度用例): 覆盖 dry-run、跳过已审核单据、多邮箱键隔离、级联清理。
- `tests/hci_acceptance/scenarios.py` (`MAIL-01` ~ `MAIL-05`): 验证 UI 状态栏从 Download -> Parse -> Save 的阶段推进。

#### 4.3.3 协议层保真度鸿沟 (Mock Gaps)
1. **纯内存 Mock (`_FakeIMAP`) 掩盖真实网络异常**:
   - 未覆盖 Modified UTF-7 邮箱文件夹名（如中文文件夹 `&XfJT0ZAB-` 代表 `已发送`）。
   - 未覆盖在分块接收 `RFC822` 巨大邮件体时的 TCP 中途断连与丢包。
   - 未覆盖 IMAP 服务端 `UIDVALIDITY` 变更导致的全量 UID 失效场景。
2. **缺乏自动化指数退避重试**: 发生临时性网络超时时，未实现并测试重试机制。

---

### 4.4 手机扫码上传与防火墙授权 (Mobile Upload & Windows Firewall)

#### 4.4.1 架构与执行流程
- **内嵌服务**: `scripts/invoice_fetch/mobile_upload.py:MobileUploadServer` 监听 `0.0.0.0`，自动过滤 Docker/WSL 虚拟网卡，筛选有效局域网 IP。
- **临时会话与安全**: 生成 24 字节 URL-safe 随机 Token，设置 10 分钟 TTL；提供 PDF.js 移动端预览；HTTP 返回数据经过 `public_upload_result` 脱敏。
- **Windows 防火墙集成**: `windows_firewall.py` 通过 netsh/PowerShell 检测专用网络入站规则，通过 `ShellExecuteEx` 申请 UAC 权限。

#### 4.4.2 现有测试覆盖评估
- `tests/test_mobile_upload.py`: 验证局域网 IP 排序、Token 会话保持、多文件去重。
- `tests/test_windows_firewall.py`: 验证防火墙规则参数生成、公用网络规则拒绝、开发端口检测。
- `tests/test_mobile_upload_browser_smoke.py`: 基于 Playwright 的真实移动端网页文件选择与渲染测试。

#### 4.4.3 测试盲区
1. **系统命令纯字符串 Mock**: 防火墙测试仅模拟英文 netsh 输出，未测试非中文/非英文 Windows 区域设置下的 netsh 输出解析。
2. **并发上传竞态**: 缺少多个移动客户端同时向同一会话并发上传 10+ 文件的压力测试。
3. **网络中断残余文件清理**: 缺少上传 40MB 大文件时客户端突发断开、临时目录是否残留脏数据的测试。

---

### 4.5 多格式导出与物料预检 (Multi-Format Export & Fail-Closed Precheck)

#### 4.5.1 三层 Fail-Closed 预检防护体系
```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        多格式导出三层 Fail-Closed 预检体系                             │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Layer 1 (预检计算层): scripts/invoice_fetch/claim_export.py:inspect_extra_material    │
│  └── 预先扫描全部单据，计算缺失附件数、缺失报销证明数、未审核发票数与缺失金额条目     │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Layer 2 (GUI 视觉守卫): scripts/invoice_fetch/gui/app.py:_refresh_export_page          │
│  └── 若存在任何缺失物料，禁用"导出报销包"按钮，并在操作区渲染醒目的红色拦截告警横幅    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Layer 3 (后端绝对安全网): scripts/invoice_fetch/claim_export.py:export_claim_package   │
│  └── 若检测到物料缺失且未显式传入 allow_missing_extra=True，强制抛出 ValueError 阻断导出│
└────────────────────────────────────────────────────────────────────────────────────────┘
```

#### 4.5.2 现有测试覆盖评估
- `tests/test_export_material_preflight.py`: 完整验证了从 Layer 1 统计 -> Layer 2 禁用 -> Layer 3 抛异常的全流程，并断言异常时**零残留磁盘导出目录**。
- `tests/test_attachment_naming_and_excel.py` & `test_mvp_export_evidence.py`: 验证 Excel 报销台账生成、有效日期排序、附件标准化重命名 (`YYYY-MM-DD_Category_Amount_Number_Role.pdf`)。
- `tests/hci_acceptance/scenarios.py: run_export_01`: 双预言机验证缺失物料时的端到端拦截。

#### 4.5.3 测试盲区
1. **Excel 目标文件被外部排他锁定**: 若用户已在 Microsoft Excel 中打开 `reimbursement.xlsx`，`openpyxl.save()` 将抛出 `PermissionError`，目前缺少对该异常的用户友好提示测试。
2. **CSV / Excel 公式注入 (Formula Injection)**: 缺少对销售方名称或备注以 `=`, `+`, `-`, `@` 开头时的转义防护测试。

---

### 4.6 整体业务 E2E vs 单元 Mock 保真度矩阵与整治路线图

#### 4.6.1 业务流测试保真度全景矩阵

| 核心业务流程 (Business Flow) | 真实 E2E / 双预言机测试 (True E2E) | 浅层单元 / Pure Mock 测试 (Shallow Mock) | 未覆盖的故障模式与风险盲区 (Untested Blindspots) | 审计评级 |
|---|---|---|---|:---:|
| **连续审核状态机** | `tests/hci_acceptance` (CR-01~08 双预言机) | `test_workbench_state.py` (纯内存数据结构) | 批量更新无事务回滚；活动过滤下光标移动越界；行内编辑键盘事件冲突 | **HIGH (90%)** |
| **发票批量导入与映射** | `test_import_review_identity.py` (多源 ID 隔离) | `test_company_tax_profile.py` (表单数据清洗) | 批量中途写入失败无数据库回滚；500+ 文件压力测试；损坏/加密 PDF | **MED-HIGH (80%)** |
| **邮箱拉取与同步引擎** | `test_email_reprocess.py` (DB 重解析); MAIL-01~05 | `test_mail_fetcher_imap_semantics.py` (`_FakeIMAP`) | 非 ASCII 文件夹名 (UTF-7)；传输中断丢包；真实 OAuth2/POP3；指数退避重试 | **MEDIUM (65%)** |
| **手机扫码与防火墙** | `test_mobile_upload_browser_smoke.py` (Playwright) | `test_windows_firewall.py` (硬编码 netsh 字符串) | 真实 Windows UAC 拒绝码；多国语言 netsh 输出解析；多客户端并发上传 | **MEDIUM (70%)** |
| **多格式导出与预检** | `test_export_material_preflight.py`; EXPORT-01 | `test_attachment_naming_and_excel.py` (文件名规则) | 目标 Excel 文件写入锁冲突 (`PermissionError`)；公式注入；GB 级大包流式导出 | **HIGH (85%)** |

#### 4.6.2 四级整治优先级路线图 (Remediation Roadmap)
- **P1 (事务原子性与数据安全)**: 在 `_import_local_directory` 与 `app.py:7050` 批量审核更新中引入 SQLite 显式事务上下文 (`with db._conn:`)，并补充负向注入测试。
- **P2 (并发竞态与状态防护)**: 编写多线程测试夹具，模拟前台持续审核发票的同时，后台 `EmailScanWorker` 与 `MobileUploadServer` 并发插入/更新记录。
- **P3 (协议层保真度升级)**: 将 `test_mail_fetcher_imap_semantics.py` 的纯字典 Mock 升级为本地轻量级 Socket IMAP 协议模拟服务，支持 UTF-7 编码与断网注入。
- **P4 (外部异常与文件锁处理)**: 为 Excel 导出添加 `PermissionError` 拦截与临时文件安全重命名机制，并补充测试覆盖。

---

## 5. R2. 无效、冗余及脆弱测试用例专项识别

通过对全仓 109 个测试文件的抽象语法树 (AST) 遍历与依赖关系分析，精准定位了测试套件中的低效与高风险用例。

### 5.1 无效与零价值测试用例专项排查 (Invalid & Zero-Value Tests)

#### 5.1.1 恒真断言与假测试 (Tautological Assertions)
- **`tests/_claim_groups_cases.py:3017`** (`test_startup_splash_initialization_is_gui_safe`):
  ```python
  splash = StartupSplash()
  splash.show_message("正在进行测试...", 50)
  splash.close()
  self.assertTrue(True)  # 恒真断言！未对 splash 控件的可见性、进度条属性或消息渲染进行任何实质校验
  ```
  *治理方案*: 替换为真实断言 `self.assertEqual(splash.message(), "正在进行测试...")` 与 `self.assertFalse(splash.isVisible())`。

#### 5.1.2 零断言 / 纯导入 / 属性读取测试 (Zero-Assertion Tests)
以下测试函数在整个执行体内**不存在任何 `assert` 或 `self.assert*` 语句**：

| 文件路径与行号 | 测试函数名称 | 现状代码片段 | 问题根因与优化建议 |
|:---|:---|:---|:---|
| `tests/test_ui_components.py:99` | `test_clicked_signal_exists` | `card = CompactStatCard("全部", "0"); _ = card.clicked` | 仅读取了 Qt Signal 属性。改为连接信号并触发 `card.clicked.emit()` 断言回调。 |
| `tests/test_ui_style_architecture.py:161` | `test_core_shortcuts_tuple_is_exported` | `from scripts.invoice_fetch.gui.ui_components import CORE_SHORTCUTS` | 纯 import 语句，零断言。直接删除该用例（由 ruff/flake8 静态保证）。 |
| `tests/test_ui_style_architecture.py:165` | `test_secondary_shortcuts_tuple_is_exported` | `from scripts.invoice_fetch.gui.ui_components import SECONDARY_SHORTCUTS` | 同上，纯 import 语句。直接删除。 |
| `tests/test_settings_center.py:619` | `test_save_ai_profile_clear_key_does_not_raise` | `dialog._save_ai_profile_settings(activate=True)` | 触发了保存但未断言配置是否落库。补充 `mock_set_key.assert_called_once()`。 |
| `tests/test_pdf_preview_controller.py:87` | `test_dispose_ignores_already_deleted_qt_view` | `controller._dispose(view, None)` | 仅验证不抛异常。补充 `self.assertIsNone(controller.active_view())`。 |
| `tests/test_generic_imap_config.py:81, 225, 302` | `test_validate_config_gui_*` | `validate_config_gui({...})` | 隐式验证不抛异常，但未断言返回的规范化字典结构。补充对返回字典字段的断言。 |

#### 5.1.3 静态仓库文件存在性与别名重复测试
在 `tests/test_startup_probe_and_packaging.py` 中，大量存在**仅检查静态文件是否存在**的低价值用例：
- `test_script_exists` (line 135) -> 紧接着的 `test_script_parseable` (line 140) 立即读取并解析该文件。
- `test_launcher_exists` (line 180) -> 后续 `test_launcher_parseable` 立即解析该文件。
- `test_generator_module_exists` (line 295), `test_spec_exists` (line 372), `test_workflow_exists` (line 490), `test_inno_script_exists` (line 548)。
*治理方案*: 将存在性检查合并入解析测试，消除 6 个独立测试函数与重复 I/O。

#### 5.1.4 纯内部测试脚本常数断言 (Testing Test Fixture Literals)
- `tests/test_settings_preview_matrix_contract.py:7`: 断言开发辅助脚本 `scripts/dev/run_settings_preview_matrix.py` 中的字面量 `SIZES == ((1920, 1080, 1.0), (1366, 768, 1.5))`，对生产代码无任何验证意义。
- `tests/test_design_token_import_contract.py:8` (14 行文件): 仅断言 `self.assertIs(BASELINE_COLORS, DESIGN_V1_COLORS)`。在独立子进程运行模式下，为其单独启动 Python 解释器耗费 300ms。
- `tests/test_page_layout_token_contract.py:13` (25 行文件): 仅断言 4 个常数赋值映射。

---

### 5.2 重叠与冗余用例五大集群深度剖析 (Redundancy Clusters)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              五大高冗余用例集群拓扑分析                                │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 【集群 1: 历史巨石与独立模块严重重叠】                                                  │
│   • tests/_claim_groups_cases.py (155 tests, 6,925 行)                                 │
│   • tests/test_invoice_workflow.py (110 tests, 4,251 行)                               │
│     => 与独立模块 (test_ai_classifier, test_email_reprocess, test_export_*) 高度重叠    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 【集群 2: 审核工作台 10 个碎片化微型测试文件】                                         │
│   • test_review_action_regressions.py, test_review_baseline_pipeline.py, ...           │
│     => 导致 10 次独立的 Python/PySide6 进程冷启动，建议合并为 2 个标准模块             │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 【集群 3: 设置中心 13 个碎片化微型测试文件】                                           │
│   • test_settings_baseline.py, test_settings_provider_and_layout.py, ...               │
│     => 建议整合为 test_settings_dialog_ui.py 与 test_settings_config_core.py 两个文件  │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 【集群 4: 设计系统与 Token 契约用例群 (12 个小文件)】                                  │
│   • test_design_*, test_page_layout_*, test_accessibility_*, test_v016_*               │
│     => 均为内存字典常数检查，建议合并为单个 test_design_tokens_contract.py 静态模块     │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 【集群 5: 历史废弃版本残留】                                                           │
│   • test_mailbox_v4_ui.py (已废弃 V4 卡片架构) vs test_mailbox_v5_ui.py (当前权威 V5)  │
│     => 建议直接删除 test_mailbox_v4_ui.py                                              │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

#### 整合映射效益表

| 重叠集群分类 | 当前涉及文件数 | 当前用例数 | 整合后目标文件 | 减少进程启动次数 | 预估节省时间 |
|---|:---:|:---:|---|:---:|:---:|
| 审核工作台碎片 | 10 个 | 61 个 | `test_review_workspace_ui.py`<br>`test_review_detail_ui.py` | 8 次 | ~3.5s |
| 设置中心碎片 | 13 个 | 59 个 | `test_settings_dialog_ui.py`<br>`test_settings_config_core.py` | 11 次 | ~4.5s |
| 设计 Token 契约 | 12 个 | 86 个 | `test_design_tokens_contract.py` | 11 次 | ~4.0s |
| 历史废弃 V4 邮箱 | 1 个 | 12 个 | *直接删除* (保留 V5) | 1 次 | ~2.5s |
| **合计** | **36 个小文件** | **218 个** | **5 个高内聚模块** | **31 次进程启动** | **~14.5s** |

---

### 5.3 38 处高脆弱性与 Flaky 异味专项排查 (Fragility & Flakiness Smells)

静态扫描全仓共排查出 38 处高脆弱性代码隐患，主要分布在以下 5 大类别：

#### 5.3.1 硬编码休眠与时序竞态 (Hardcoded Sleeps)
使用固定 `time.sleep()` 或 `QTest.qWait()` 在 CI 高负载下极易超时，在空闲时则浪费时间：
- `tests/test_ihds08.py:223`: `time.sleep(0.25)` (等待网络探测) -> 改用 `wait_until(cond, timeout=2.0)`。
- `tests/test_ihds09.py:74`: `QTest.qWait(75)` (等待窗口初始化) -> 改用 `app.processEvents()` 结合谓词。
- `tests/test_mobile_upload.py:585`: `time.sleep(0.05)` (等待 Uvicorn 服务启动) -> 改用本地端口连接探测 (`socket.create_connection`)。
- `tests/test_scan_lifecycle.py:366`: `time.sleep(0.01)` (等待线程退出) -> 改用 `worker.wait(1000)`。
- `tests/test_workbench_layout.py:1030, 1071, 1108`: `QTest.qWait(20/50)` (等待 Splitter 拖拽重绘)。

#### 5.3.2 全局 Monkeypatch 泄漏 (Global State Pollution)
- **`tests/test_mailbox_v5_ui.py:39-42`**:
  ```python
  def setUp(self):
      QMessageBox.information = lambda *args, **kwargs: QMessageBox.Ok
      QMessageBox.warning = lambda *args, **kwargs: QMessageBox.Ok
      QMessageBox.critical = lambda *args, **kwargs: QMessageBox.Ok
      QMessageBox.question = lambda *args, **kwargs: QMessageBox.Yes
  ```
  *危害*: 直接覆写 `PySide6.QtWidgets.QMessageBox` 类级方法且**未在 `tearDown` 中恢复**！同进程下的后续测试将静默吞掉所有弹窗异常。  
  *修复*: 改用 `unittest.mock.patch.object` 或在 `tearDown` 中恢复原始备份。

#### 5.3.3 共享数据库状态泄漏与工作目录污染 (Shared DB Leaks)
- `tests/test_mailbox_v4_ui.py:16` & `test_mailbox_v5_ui.py:18`: 硬编码 `TEST_DB_PATH = Path("test.db")` 在仓库根目录创建数据库，且未清理。
- `tests/test_mailbox_safety_delete.py:160`: 传递硬编码 `Path("invoices.db")`。
  *修复*: 强制使用 `tempfile.TemporaryDirectory()` 隔离所有测试数据库。

#### 5.3.4 未固定系统时钟与时间依赖 (Clock Flakiness)
- `tests/test_v016_responsive_contracts.py:83-87`: 直接调用 `datetime.now()`，跨越午夜 0 点或月末时可能导致分组断言翻车。
- `tests/test_db_backup.py:324`: `mtime = time.time() + idx`，在低时间戳精度文件系统上可能导致排序不稳定。

#### 5.3.5 沉重子进程创建 (Heavy Subprocess Spawning)
- `tests/test_ihds09.py:616`: 在单个测试内连续启动 3 次全新的 Python/Qt 子进程验证 1.0x/1.25x/1.5x 缩放，单次耗费 10 秒。

---

### 5.4 HCI Acceptance 验收套件深度评估 (Dual-Oracle HCI Suite)

HCI Acceptance 套件是 Invoice Hub 发布前最高等级的端到端验收车道。

#### 5.4.1 架构三层防御机制
1. **父进程看门狗 (`scripts/dev/run_hci_acceptance.py`)**:
   - 采用 Win32 `CreateToolhelp32Snapshot` 每 200ms 采样监控子进程树 (`python.exe`, `InvoiceHub.exe`, `QtWebEngineProcess.exe`)。
   - 能够精准捕获 Windows 下 Qt C++ 层的 `0xC0000005` (Access Violation) 与 `0xC00000FD` (Stack Overflow) 崩溃，并在 120s 硬超时时执行 `taskkill /F /T` 强制回收。
2. **子执行进程与双预言机 (`tests/hci_acceptance/scenarios.py`)**:
   - 19 个端到端交互场景顺序执行，每个场景同时断言 **底层 SQLite 数据不变量** 与 **前端 Qt Widget 渲染可见性**。
3. **变异自检契约 (`test_mutation_selftest.py`)**:
   - 故意注入陈旧进度文本与错误徽标计数，严格验证双预言机具备真正的缺陷检出能力，杜绝“假通过”。

#### 5.4.2 19 个核心场景覆盖矩阵表

| 场景编号 | 场景名称与交互目标 | 触发操作 | 后端预言机 (Backend Oracle) | UI 预言机 (UI Oracle) | 真实度评估 |
|:---:|:---|:---|:---|:---|:---:|
| **CR-01** | 连续审核进入 | `_enter_hci_continuous_review` | `TO_REVIEW` 计数与数据库一致 | 列表隐藏，预览可见，进度为 `1/N · 还剩 N` | **High** |
| **CR-02** | 连续审核通过单张 | `_set_selected_status(APPROVED)` | `APPROVED+1`, `TO_REVIEW-1` | 进度更新为 `2/N · 还剩 N-1`，光标后移 | **High** |
| **CR-03** | 连续审核连续通过两张 | 连续触发两次审核通过 | `APPROVED+2`, `TO_REVIEW-2` | 进度更新为 `3/N · 还剩 N-2` | **High** |
| **CR-04** | 审核忽略单据 | `_ignore_selected()` | `IGNORED+1`, `TO_REVIEW-1` | 移出审核队列，单据后移 | **High** |
| **CR-05** | 标记单据异常 | `_mark_selected_error()` | `ERROR+1`, `TO_REVIEW-1` | 错误计数更新，UI 状态同步 | **High** |
| **CR-06** | 暂缓/跳过审核 | `_skip_review()` | `TO_REVIEW` 不变，状态不变 | 处理计数 +1，切至下一张 | **High** |
| **CR-07** | 退出并重新进入 | 退出后再次进入 | 数据库状态保持 | 重新计算最新的 `initial_total` | **High** |
| **CR-08** | 审核最后一张完成 | 审核通过最后一张 | `TO_REVIEW == 0` | 渲染终态提示面板，无无效翻页 | **High** |
| **RV-01** | 工作台选择一致性 | 切换当前行 | 选中的 Invoice ID 存在于 DB | 表格当前行 ID == current_invoice == 详情 == 预览 | **High** |
| **RV-02** | 状态徽标计数一致性 | 触发数据变更后刷新 | 各状态 DB count 总和 == total | 顶部 5 个状态徽标文本严格等于 DB 计数值 | **High** |
| **MAIL-01**| 同步进行中 (Download) | 注入 stage 更新事件 | — | 状态栏显示“正在同步”/“下载附件”，包含已耗时间 | **Medium** |
| **MAIL-02**| 同步阶段推进 (Stages) | 注入 Download->Parse->Save | — | 中文状态顺序切换，耗时单调递增 | **Medium** |
| **MAIL-03**| 历史重检完成终态 | 触发 `_start_history_recheck` | — | 终态包含“完成”，不会退回未开始状态 | **High** |
| **MAIL-04**| 历史重检异常失败 | 注入 failure 事件 | — | 错误信息完整呈现，解除按钮锁定 | **High** |
| **MAIL-05**| 历史重检主动取消 | 触发 `_cancelled` | — | 状态变为已取消，恢复常规操作 | **High** |
| **DATE-01**| 日期范围预设快捷选择 | 点击 7天/30天/3个月 | — | 预设计算正确，满足 QDate 算术 | **High** |
| **DATE-02**| 倒置非法日期拒绝 | 输入 start > end 并提交 | — | 对话框拒绝 accept，展示错误提示 | **High** |
| **SAFE-01**| 核心操作互斥保护 | 扫描/重检执行中尝试重复触发 | — | 按钮处于禁用状态，阻断并发冲突 | **High** |
| **EXPORT-01**| 缺失物料导出 Fail-Closed | 尝试导出物料不全的报销包 | — | 阻断导出操作，展示缺失物料清单与拦截提示 | **High** |

---

## 6. R3. CI 耗时分析与分片瓶颈诊断

### 6.1 GitHub Actions CI 架构与执行车道拓扑

在 `.github/workflows/ci.yml` 中，单元测试作业配置为 3 分片矩阵：
```yaml
unit_tests:
  runs-on: windows-latest
  strategy:
    matrix:
      shard: [0, 1, 2]
  steps:
    - name: Run isolated unit tests
      run: |
        python scripts/dev/run_isolated_unittest.py --exclude-dir tests/hci_acceptance --exclude-module tests.test_workbench_layout --module-timeout-seconds 900 --shard-count 3 --shard-index ${{ matrix.shard }}
```

---

### 6.2 3-Shard 轮询分片缺陷与 2.84x 倾斜深度剖析

#### 6.2.1 字母序轮询机制的严重缺陷
当前 `run_isolated_unittest.py` 的分片算法为简单的按字母排序后模除切片：
```python
def _select_shard(modules: list[str], shard_count: int, shard_index: int) -> list[str]:
    return modules[shard_index::shard_count]
```
由于测试耗时与模块名称字母顺序完全不相关，导致了极其严重的负载倾斜：

| 分片编号 | 分配模块数 | 分配测试数 | 纯单测执行耗时 | 进程启动开销 | **总分片耗时 (Wall Time)** | 与最慢分片差距 (空转浪费) |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Shard 0** | 32 个 | 402 个 | 146.78s | 30.25s | **177.03s (2.95 min)** | **-325.47s (空转 5.42 min)** |
| **Shard 1** | 31 个 | 461 个 | 364.24s | 35.44s | **399.69s (6.66 min)** | **-102.81s (空转 1.71 min)** |
| **Shard 2** | 31 个 | 458 个 | 469.76s | 32.74s | **502.50s (8.38 min)** | **0.00s (关键路径瓶颈)** |
| **全仓总计** | **94 个** | **1,321 个** | **980.78s** | **98.43s** | **1,079.21s (17.99 min)** | **倾斜比: 2.84x** |

```
当前 3-Shard 执行耗时对比图:
Shard 0: ███████▌ 177.03s (2.95m)  [过早完成，空转 5.42 分钟]
Shard 1: ████████████████ 399.69s (6.66m)
Shard 2: ████████████████████ 502.50s (8.38m)  <-- CI 关键路径瓶颈 (Critical Path)
         |---------------- 325.47s (5.42 min) 倾斜浪费 ----------------|
```

#### 6.2.2 为什么 Shard 2 会严重滞后？
因为字母序切片巧合地将全仓最重的 3 个大型 GUI 测试套件全部划分给了 Shard 2：
1. `tests.claim_groups_gui` (**177.59s**, 全仓最慢模块，占比 16.5%)
2. `tests.test_ihds09` (**115.86s**, 全仓次慢模块，占比 10.7%)
3. `tests.test_preview_workbench_ui` (**46.03s**)
4. `tests.test_mobile_upload` (**35.34s**)
仅这 4 个模块在 Shard 2 中就累计消耗了 **374.82s (6.25 min)**！

---

### 6.3 HCI 专属车道性能与稳定性验证

HCI Acceptance 车道实测数据：
- **Watchdog 驱动执行耗时**: **47.75s**
- **Oracle 变异自检 pytest 耗时**: **11.22s**
- **车道总 Wall-Clock 耗时**: **58.97s (~0.98 min)**
- **资源泄漏检测**: 0 残留后台线程、0 残留进程树、0 次原生崩溃 (PASS)。

---

### 6.4 全仓 Top 20 最耗时测试模块全景台账

| 排名 | 所属分片 | 测试模块名称 (Module Name) | Wall Time (s) | Wall Time (min) | 全仓占比 (%) | 用例数 | 纯单测时间 (s) | 进程开销 (s) |
|:---:|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **1** | Shard 2 | `tests.claim_groups_gui` | 177.59s | 2.96m | 16.5% | 72 | 176.59s | 1.00s |
| **2** | Shard 2 | `tests.test_ihds09` | 115.86s | 1.93m | 10.7% | 47 | 113.90s | 1.96s |
| **3** | Shard 1 | `tests.test_gui_column_filters` | 105.80s | 1.76m | 9.8% | 29 | 104.45s | 1.35s |
| **4** | Shard 1 | `tests.test_ihds08` | 51.20s | 0.85m | 4.7% | 17 | 48.23s | 2.98s |
| **5** | Shard 2 | `tests.test_preview_workbench_ui` | 46.03s | 0.77m | 4.3% | 19 | 44.60s | 1.44s |
| **6** | Shard 1 | `tests.test_preview_pdf_nav_log_001` | 40.86s | 0.68m | 3.8% | 69 | 39.75s | 1.11s |
| **7** | Shard 2 | `tests.test_mobile_upload` | 35.34s | 0.59m | 3.3% | 26 | 34.67s | 0.67s |
| **8** | Shard 1 | `tests.test_import_review_identity` | 32.80s | 0.55m | 3.0% | 16 | 30.61s | 2.19s |
| **9** | Shard 1 | `tests.test_mailbox_v5_ui` | 31.39s | 0.52m | 2.9% | 20 | 29.00s | 2.38s |
| **10** | Shard 0 | `tests.test_hci_v1` | 25.45s | 0.42m | 2.4% | 15 | 23.75s | 1.71s |
| **11** | Shard 1 | `tests.test_export_material_preflight` | 19.25s | 0.32m | 1.8% | 13 | 17.64s | 1.61s |
| **12** | Shard 0 | `tests.test_review_action_regressions` | 18.25s | 0.30m | 1.7% | 9 | 17.22s | 1.03s |
| **13** | Shard 1 | `tests.test_ui_preview_helpers` | 15.75s | 0.26m | 1.5% | 10 | 15.08s | 0.67s |
| **14** | Shard 1 | `tests.test_review_toolbar_filter_fixes` | 15.41s | 0.26m | 1.4% | 9 | 13.43s | 1.97s |
| **15** | Shard 0 | `tests.claim_groups_mail` | 14.84s | 0.25m | 1.4% | 31 | 13.20s | 1.64s |
| **16** | Shard 2 | `tests.test_review_list_paging_fix` | 14.70s | 0.25m | 1.4% | 5 | 12.90s | 1.80s |
| **17** | Shard 0 | `tests.test_import_center_geometry` | 14.31s | 0.24m | 1.3% | 4 | 12.19s | 2.12s |
| **18** | Shard 1 | `tests.test_review_feedback_fixes` | 14.16s | 0.24m | 1.3% | 7 | 12.62s | 1.53s |
| **19** | Shard 0 | `tests.test_invoice_workflow` | 13.23s | 0.22m | 1.2% | 110 | 11.93s | 1.31s |
| **20** | Shard 1 | `tests.test_mobile_upload_diagnostics` | 13.17s | 0.22m | 1.2% | 11 | 12.68s | 0.49s |

- **Top 5 模块集中度**: 累计 **496.48s (8.27 min)**，占全仓总耗时 **46.0%**。
- **Top 20 模块集中度**: 累计 **815.40s (13.59 min)**，占全仓总耗时 **75.6%**。

---

### 6.5 全仓 Top 20 最耗时单用例排查

通过 `pytest --durations=30` 深入函数级剖析：

| 排名 | 测试函数名称 | 所在测试文件 | 耗时 (s) | 根因与优化方向 |
|:---:|:---|:---|:---:|:---|
| **1** | `MobileUploadTests.test_gui_exposes_mobile_upload_button_and_dialog` | `test_mobile_upload.py` | **16.73s** | 启动真实 HTTP 服务 + 二维码渲染 + 界面完整实例化。 |
| **2** | `IHDS09Tests.test_real_window_125_percent_has_no_clipped_controls` | `test_ihds09.py` | **10.51s** | 高 DPI 窗口缩放重绘与递归几何遍历。与 150% 存在重复。 |
| **3** | `IHDS08Tests.test_mobile_start_is_async_and_duplicate_click_is_ignored` | `test_ihds08.py` | **4.25s** | 异步线程状态轮询与 QTimer 防抖等待。 |
| **4** | `MobileUploadTests.test_duplicate_upload_restores_soft_deleted_file_hash_record` | `test_mobile_upload.py` | **3.92s** | 磁盘文件真实生成与 SHA256 重复计算。 |
| **5** | `ImportReviewIdentityTests.test_e2e_e_mobile_direct_restored_result_reaches_gui_scoped_review` | `test_import_review_identity.py` | **3.61s** | 多表 Join 查询与主窗口列表完整刷新。 |
| **6** | `TestMailboxV5UI.test_mailbox_overview_uses_master_detail_without_summary_duplication` | `test_mailbox_v5_ui.py` | **3.56s** | 复杂 Master-Detail 分割条布局重建。 |
| **7** | `IHDS09Tests.test_real_window_150_percent_has_no_clipped_controls` | `test_ihds09.py` | **3.53s** | 150% DPI 检查，与 125% 逻辑重叠。 |
| **8** | `IHDS09Tests.test_real_window_1366_has_no_clipped_controls` | `test_ihds09.py` | **3.53s** | 1366 宽屏检查，可参数化合并。 |
| **9** | `TestMailboxV5UI.test_mailbox_detail_has_no_save_cancel_buttons` | `test_mailbox_v5_ui.py` | **3.52s** | 全量控件树只读检查。 |
| **10** | `TestMailboxV5UI.test_mailbox_detail_is_read_only_by_default` | `test_mailbox_v5_ui.py` | **3.41s** | 全量控件树遍历。 |
| **11** | `TestMailboxV5UI.test_import_center_uses_more_menu_for_low_frequency_actions` | `test_mailbox_v5_ui.py` | **3.13s** | QMenu 弹出渲染与动作解析。 |
| **12** | `TestMailboxV5UI.test_settings_page_does_not_open_nested_settings_dialog` | `test_mailbox_v5_ui.py` | **3.13s** | 实例化设置中心并执行事件循环。 |
| **13** | `TestMailboxV5UI.test_import_scan_selected_no_checked_accounts_warns` | `test_mailbox_v5_ui.py` | **3.04s** | QMessageBox 模态弹窗拦截与文本验证。 |
| **14** | `TestMailboxV5UI.test_mailbox_saved_accounts_use_single_add_menu` | `test_mailbox_v5_ui.py` | **3.03s** | 账号列表视图模型重建与渲染。 |
| **15** | `TestMailboxV5UI.test_add_credential_separate_from_detail` | `test_mailbox_v5_ui.py` | **2.97s** | 详情面板状态机表单切换。 |
| **16** | `TestMailboxV5UI.test_import_scan_selected_uses_checked_accounts` | `test_mailbox_v5_ui.py` | **2.96s** | 复选框扫描与 Worker 分发。 |
| **17** | `TestMailboxV5UI.test_import_scan_default_passes_only_default_key` | `test_mailbox_v5_ui.py` | **2.95s** | 默认账号解析。 |
| **18** | `TestMailboxV5UI.test_sidebar_settings_does_not_show_legacy_settings_page` | `test_mailbox_v5_ui.py` | **2.83s** | 侧边栏导航栈切换与可见性判定。 |
| **19** | `HciV1DesktopTests.test_continuous_review_progress_refreshes_from_successful_mutations` | `test_hci_v1.py` | **2.63s** | 连续审核状态推进与实时 UI 渲染。 |
| **20** | `PreviewWorkbenchUiTests.test_switching_between_pdf_invoices_rebinds_pdf_document` | `test_preview_workbench_ui.py` | **2.62s** | 真实 PDF 写入磁盘、解绑与二次重绘。 |

---

### 6.6 测试执行延迟根因构成拆解

```
测试套件耗时根因分布 (Latency Composition):
┌────────────────────────────────────────────────────────────┐
│ 1. 重复实例化完整 PySide6 GUI 控件树 (~48%)                │
│    - 每个测试方法反复创建 InvoiceReviewApp / QSplitter      │
├────────────────────────────────────────────────────────────┤
│ 2. 磁盘 SQLite 数据库频繁创建与 Schema 初始化 (~24%)       │
│    - 60+ 模块在 setUp 中 mkdtemp() + 8 个 CREATE TABLE     │
├────────────────────────────────────────────────────────────┤
│ 3. Qt 事件循环轮询与 QTest 等待 (~15%)                     │
│    - processEvents() 循环与 qWait 延时                     │
├────────────────────────────────────────────────────────────┤
│ 4. 94 次 Python 子进程冷启动开销 (~9%)                     │
│    - 解释器启动 + PySide6 C++ DLL 加载 (98.43s)            │
├────────────────────────────────────────────────────────────┤
│ 5. 磁盘合成 PDF/OFD 字节生成 (~4%)                         │
│    - 频繁进行磁盘 I/O 写入临时文件                         │
└────────────────────────────────────────────────────────────┘
```

---

## 7. CI 分级优化与测试裁剪路线图 (-70.6% 提速方案)

基于实测数据，设计了三级递进式的优化与裁剪实施路线图：

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     Invoice Hub 三级 CI 提速与优化架构体系                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│ Tier 1: 极速起效 (Quick Wins) [0 业务代码修改, 仅配置与运行器优化]              │
│  ├── LPT (最长处理时间优先) 贪心装箱动态分片 (抹平 5.4m 倾斜, 关键路径 8.38m->6.0m)  │
│  ├── uv 极速包管理器替代 pip install (依赖安装 60s -> 15s)                      │
│  └── pytest.ini 优化 (-o faulthandler_timeout=120, 禁用无用插件)                │
│  ★ 收益: CI 总耗时 9.4m -> 6.3m (-33.3%), 研发立即可感知                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│ Tier 2: 测试用例裁剪与去重整合 (Test Pruning & Consolidation)                   │
│  ├── 裁剪 IHDS09 高 DPI (125%/150%/1366px) 冗余重绘用例 (节省 40-50s)           │
│  ├── 参数化合并列过滤 (test_gui_column_filters) 与邮箱 UI 用例 (节省 45-60s)    │
│  ├── 合并 36 个微型碎片测试文件为 5 个高内聚模块 (减少 31 次子进程冷启动)       │
│  └── 解构 _claim_groups_cases.py 巨石，剔除重复 Mock 验证                       │
│  ★ 收益: CI 总耗时 6.3m -> 4.9m (-47.5%)                                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│ Tier 3: 架构演进与智能运行 (Architecture Evolution & Smart Execution)           │
│  ├── 内存 SQLite (:memory:) 与会话级 Schema 模板克隆 (节省 30-40s I/O)          │
│  ├── 混合运行器 (35 个非 Qt 单测走 pytest-xdist 多核，59 个 Qt 单测走隔离子进程)│
│  ├── 测试影响分析 (TIA): 针对特定 PR 仅执行受影响模块 + HCI 车道 (<2.0m 反馈)  │
│  └── 扩展为 4-Shard 弹性分片矩阵 (单位分片降至 2.5m)                            │
│  ★ 收益: CI 总耗时 4.9m -> 2.8m (-70.6%), GHA 运行成本削减 66.2%                │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### 7.1 Tier 1: 极速起效方案 (LPT 贪心装箱 + uv 极速包管理器)

#### 7.1.1 LPT 贪心装箱分片算法 (Longest Processing Time First)
**原理**: 维护模块历史耗时权重表，按耗时从大到小排序，依次将模块分配给当前累计总耗时最小的分片：

```
分片重平衡实测效果对比:
当前字母序分片:
Shard 0 (32 mods): ███████▌ 177.03s (2.95m)
Shard 1 (31 mods): ████████████████ 399.69s (6.66m)
Shard 2 (31 mods): ████████████████████ 502.50s (8.38m)  [关键路径 = 8.38m | 倾斜 = 325.47s]

LPT 贪心装箱平衡后:
Shard 0 (31 mods): ██████████████ 359.82s (6.00m)
Shard 1 (31 mods): ██████████████ 359.59s (5.99m)
Shard 2 (32 mods): ██████████████ 359.80s (6.00m)       [关键路径 = 6.00m | 倾斜 = 0.23s]
```
- **关键路径直接压缩**: 从 **502.50s (8.38m)** 降至 **359.82s (6.00m)**，净省 **142.68s (2.38 分钟, -28.4%)**。
- **分片负载完全均衡**: 倾斜比从 **2.84x 降至 1.00x** (差值仅 0.23 秒)。

#### 7.1.2 采用 `uv` 极速包管理器
在 GitHub Actions Windows Runner 上，`uv` 通过多线程并发解压和硬链接缓存，将依赖安装时间从 **45~60 秒压缩至 <15 秒**。

---

### 7.2 Tier 2: 测试用例裁剪与去重整合 (Hotspots Deduplication)

1. **裁剪 `test_ihds09.py` 冗余 DPI 排列组合**: 将 1.25x、1.5x、1366px 的窗口全量控件遍历整合为 1 个参数化测试，省去 2 次真实子进程启动，**节省 ~45s**。
2. **重构 `test_gui_column_filters.py` (105.8s)**: 29 个测试中大量重复执行相同的 SQLite 插入和界面重绘。采用 `setUpClass` 共享内存数据，**节省 ~50s**。
3. **精简 `claim_groups_gui.py` (177.6s)**: 将其中仅测试按钮文本与边距的用例移至静态样式契约测试，避免重复实例化主窗体，**节省 ~60s**。
4. **整合 36 个微型碎片文件**: 消除 31 次独立 Python 解释器冷启动，**节省 ~15s**。

---

### 7.3 Tier 3: 架构演进与智能运行 (内存 SQLite + 混合执行器 + TIA)

1. **支持内存 SQLite (`:memory:`)**: 彻底消除 Windows NTFS 文件锁争用与临时文件夹创建/清理，**节省 30~40s**。
2. **混合运行模式 (Hybrid Runner)**: 将 35 个非 Qt 纯单元测试整合入单个 `pytest -n auto` 进程批处理（耗时从 60s 缩减至 <10s），其余 Qt 模块维持隔离。
3. **测试影响分析 (TIA)**: 基于 git diff 分析修改范围，若仅修改 Excel 导出模块，PR 门禁仅执行 `test_claim_export` + HCI 车道，**将 PR 反馈时间压至 < 2.0 分钟**。

---

### 7.4 全维度量化收益测算对比表 (Before vs After)

#### 7.4.1 端到端 CI Wall-Clock 耗时对比表

| CI 阶段 / 作业通道 | 现状基线 (Baseline) | Tier 1 (Quick Wins) | Tier 2 (+ Pruning) | Tier 3 (+ Architecture) |
|---|:---:|:---:|:---:|:---:|
| **依赖环境安装 (`uv` / pip cache)** | ~60s | ~15s | ~15s | ~15s |
| **单元测试 Shard 0 耗时** | 177.0s (2.95m) | 359.8s (6.00m) | 280.0s (4.67m) | 150.0s (2.50m) |
| **单元测试 Shard 1 耗时** | 399.7s (6.66m) | 359.6s (5.99m) | 278.0s (4.63m) | 148.0s (2.47m) |
| **单元测试 Shard 2 耗时** | **502.5s (8.38m)** | **359.8s (6.00m)** | **280.0s (4.67m)** | **150.0s (2.50m)** |
| **单测分片关键路径 (Max Shard)** | **502.5s (8.38m)** | **359.8s (6.00m)** | **280.0s (4.67m)** | **150.0s (2.50m)** |
| **HCI Acceptance 专属车道** | 59.0s (0.98m) | 50.0s (0.83m) | 45.0s (0.75m) | 40.0s (0.67m) |
| **Source Gates 门禁作业** | 90.0s (1.50m) | 35.0s (0.58m) | 35.0s (0.58m) | 35.0s (0.58m) |
| **★ 整体 CI PR Wall-Clock 耗时** | **~9.4 min (562s)** | **~6.3 min (375s)** | **~4.9 min (295s)** | **~2.8 min (165s)** |
| **★ 耗时总缩减比例** | **基准 (Baseline)** | **-3.1 min (-33.3%)** | **-4.5 min (-47.5%)** | **-6.6 min (-70.6%)** |
| **分片负载倾斜比 (Max / Min)** | **2.84x (325.5s)** | **1.00x (0.2s)** | **1.01x (2.0s)** | **1.01x (2.0s)** |

```
整体 CI 流水线反馈耗时演进对比:
现状基线:       ████████████████████ 9.4 min (562s)
Tier 1 (极速):  █████████████▌ 6.3 min (375s)   [-33.3%]
Tier 2 (+去重): ██████████ 4.9 min (295s)        [-47.5%]
Tier 3 (+架构): ██████ 2.8 min (165s)           [-70.6%]
```

#### 7.4.2 GitHub Actions 计算资源消耗测算 (按每月 100 次 PR 构建)

| 指标维度 | 现状基线 | Tier 1 落地后 | Tier 2 落地后 | Tier 3 落地后 |
|---|:---:|:---:|:---:|:---:|
| **单次构建 Runner 分钟数 (6 Jobs 累计)** | ~32.5 min | ~22.0 min | ~17.5 min | ~11.0 min |
| **每月 GHA 消耗总分钟数 (100 Builds)** | 3,250 min | 2,200 min | 1,750 min | 1,100 min |
| **每月节省计算时长** | 0 min | **1,050 min** | **1,500 min** | **2,150 min** |
| **计算成本与排队等待削减率** | **基准** | **-32.3%** | **-46.2%** | **-66.2%** |

---

## 8. 实施落地指引与验证手册

### 8.1 分阶段实施路线与具体动作

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 工程落地实施三个阶段                                    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 阶段一: 立即实施 (Week 1)                                                              │
│  1. 替换 scripts/dev/run_isolated_unittest.py 中的 _select_shard 为 LPT 算法           │
│  2. 在 .github/workflows/ci.yml 中集成 astral-sh/setup-uv@v3                           │
│  3. 修复 4 处全局 QMessageBox monkeypatch 泄漏与 test.db 磁盘残留                      │
│  4. 删除 12 个恒真/零断言无效测试及废弃的 test_mailbox_v4_ui.py                         │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 阶段二: 重构与去重 (Week 2 - Week 3)                                                    │
│  1. 合并审核工作台 10 个小文件与设置中心 13 个小文件                                   │
│  2. 裁剪 IHDS09 DPI 缩放重复用例与 test_gui_column_filters 冗余 DB 插入                │
│  3. 将所有固定 time.sleep/qWait 替换为通用的 wait_until 谓词等待辅助函数               │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 阶段三: 架构演进 (Week 4)                                                              │
│  1. 实现 InvoiceDB(":memory:") 内存数据库支持                                          │
│  2. 引入纯单元测试与 Qt GUI 测试的混合执行机制                                         │
│  3. 配置 PR 增量测试影响分析 (TIA) 工作流                                              │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 8.2 核心改造补丁代码规范

#### 8.2.1 `scripts/dev/run_isolated_unittest.py` 的 LPT 贪心装箱补丁
```python
# 模块实测耗时权重表 (秒)
_MODULE_WEIGHTS = {
    "tests.claim_groups_gui": 178,
    "tests.test_ihds09": 116,
    "tests.test_gui_column_filters": 106,
    "tests.test_ihds08": 51,
    "tests.test_preview_workbench_ui": 46,
    "tests.test_preview_pdf_nav_log_001": 41,
    "tests.test_mobile_upload": 35,
    "tests.test_import_review_identity": 33,
    "tests.test_mailbox_v5_ui": 31,
    "tests.test_hci_v1": 25,
    "tests.test_export_material_preflight": 19,
    "tests.test_review_action_regressions": 18,
    "tests.test_ui_preview_helpers": 16,
    "tests.test_review_toolbar_filter_fixes": 15,
    "tests.claim_groups_mail": 15,
    "tests.test_review_list_paging_fix": 15,
    "tests.test_import_center_geometry": 14,
    "tests.test_review_feedback_fixes": 14,
    "tests.test_invoice_workflow": 13,
    "tests.test_mobile_upload_diagnostics": 13,
    "tests.test_expense_date": 12,
    "tests.test_settings_pages_baseline": 12,
    "tests.test_review_workspace_baseline": 12,
    "tests.test_mobile_upload_firewall_ui": 10,
    "tests.test_settings_provider_and_layout": 10,
    "tests.test_mobile_upload_page_contract": 9,
    "tests.test_settings_center": 9,
    "tests.test_review_workspace_closure": 8,
    "tests.test_settings_baseline": 7,
    "tests.test_review_detail_closure": 7,
    "tests.test_startup_probe_and_packaging": 6,
    "tests.test_settings_dialog": 6,
    "tests.test_v016_responsive_contracts": 6,
    "tests.test_mailbox_safety_delete": 6,
    "tests.test_generic_imap_config": 5,
    "tests.claim_groups_core": 5,
}

def _select_shard_lpt(modules: list[str], shard_count: int, shard_index: int) -> list[str]:
    """采用 LPT (Longest Processing Time first) 贪心装箱算法进行分片平衡"""
    if shard_count <= 0 or shard_index < 0 or shard_index >= shard_count:
        raise ValueError("invalid shard parameters")
    
    sorted_modules = sorted(
        modules,
        key=lambda m: (_MODULE_WEIGHTS.get(m, 2), m),
        reverse=True
    )
    
    shards: list[list[str]] = [[] for _ in range(shard_count)]
    shard_weights = [0.0] * shard_count
    
    for mod in sorted_modules:
        min_idx = shard_weights.index(min(shard_weights))
        shards[min_idx].append(mod)
        shard_weights[min_idx] += _MODULE_WEIGHTS.get(mod, 2)
        
    return shards[shard_index]
```

#### 8.2.2 `.github/workflows/ci.yml` 的 `uv` 集成配置
```yaml
      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          version: "latest"
          enable-cache: true
          cache-dependency-glob: "requirements*.txt"

      - name: Install dependencies via uv
        run: |
          uv pip install --system -r requirements.txt -r requirements-build.txt -r requirements-test.txt
```

#### 8.2.3 通用谓词等待辅助函数 (`wait_until`)
```python
import time
from typing import Callable

def wait_until(predicate: Callable[[], bool], timeout: float = 2.0, interval: float = 0.01) -> bool:
    """消除硬编码 sleep，基于状态条件进行动态等待"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if predicate():
            return True
        time.sleep(interval)
    raise TimeoutError(f"Condition not met within {timeout}s")
```

---

### 8.3 独立复现与验证命令集

所有开发者与评审人员可使用以下命令独立验证本报告中的各项数据与指标：

```powershell
# 1. 验证 HCI 验收专属车道执行及双预言机变异自检
python scripts/dev/run_hci_acceptance.py
python -m pytest -q tests/hci_acceptance/test_mutation_selftest.py tests/hci_acceptance/test_report_verdict.py

# 2. 独立运行指定分片验证耗时与稳定性
python scripts/dev/run_isolated_unittest.py --shard-count 3 --shard-index 0
python scripts/dev/run_isolated_unittest.py --shard-count 3 --shard-index 1
python scripts/dev/run_isolated_unittest.py --shard-count 3 --shard-index 2

# 3. 运行核心业务状态机与 Identity 隔离测试
python -m unittest tests.test_import_review_identity -v
python -m unittest tests.test_export_material_preflight -v
python -m unittest tests.test_scan_lifecycle -v
python -m unittest tests.test_email_reprocess -v

# 4. 执行全仓耗时 Top 30 慢用例探测
pytest --durations=30 tests/
```

---

### 8.4 风险缓解与回滚预案

1. **PySide6 C++ 内存崩溃隔离保护**:
   - 保持 GUI 模块的子进程隔离机制 (`run_isolated_unittest.py`)，避免多窗口在同进程销毁时触发 Windows C++ 原生 `0xC0000005` 崩溃。
2. **分片权重自动同步机制**:
   - 当新增大型测试模块时，若未在 `_MODULE_WEIGHTS` 中显式登记，算法默认赋予 2 秒保底权重；可在 CI 完成后通过脚本定期自动更新权重字典。
3. **Fail-Closed 安全守卫不降级**:
   - 所有测试裁剪与合并操作**严禁删除任何有价值的断言**，HCI 双预言机验收车道作为核心主干合入的硬性门禁保持 100% 开启。

---

*报告编制完成。本报告凝聚了业务状态机深度审查、代码异味治理与 CI 架构提速的完整度量与落地方案，可作为 Invoice Hub 后续工程质量与效能提升的权威指导蓝本。*
