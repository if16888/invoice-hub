# GUI 技术债收敛计划（v0.3 前置）

> 本文件记录 2026-10-31 的盘点结果与退休批次。策略基线以 `scripts/check_architecture_policy.py` 与 `docs/architecture.md` 为准；**删模块必须同 PR 收缩基线**，且行为级测试必须保留。

## 1. 盘点快照

基线：`master` @ `6c88934`。`scripts/invoice_fetch/gui/` 共 **33,799 行**（85 个模块）。

| 类别 | 模块 | 行数 |
|---|---|---|
| 架构策略冻结的补丁模块（14 个） | `business_pages_baseline.py`、`design_baseline_styles.py`、`design_v1_review_task_closure.py`、`hci_v1_closure.py`、`review_baseline_pipeline.py`、`review_feedback_fixes.py`、`review_legacy_contract.py`、`review_settings_issue_fixes.py`、`review_toolbar_filter_fixes.py`、`review_workspace_baseline.py`、`settings_baseline.py`、`settings_legacy_contract.py`、`settings_pages_baseline.py`、`ui_visibility_contracts.py` | **5,135** |
| 兼容基线引擎 | `hci_v1.py` | 1,107 |
| 设计规范兼容层 | `design_system_v11.py` | 339 |
| 死代码（产品从不实例化） | `settings_dialog.py` | **3,901** |
| 死代码（零引用，已删） | `mobile_upload_dialog.py` | 204 |
| 兼容 re-export 壳（已删） | `buyer_warning_readability.py` | 39 |
| 重复 token 层 | `styles.py`（第二套 `COLOR_TOKENS`/`TYPE_*`，与 `design_tokens.py` 冲突） | 影响全站 QSS |

债务合计 **约 10,725 行，占 GUI 的 32%**。另有 3 个冻结的 hidden-compat scope（`FROZEN_HIDDEN_COMPAT_SCOPES`）。

## 2. 治理规则

- 新功能写进**归属领域模块或标准复用组件**，禁止新增 `*_closure.py` / `*_fix.py` / `*_fixes.py` / `*_baseline_pipeline.py`。
- 退休顺序：确认零引用（import / 构造 / 动态引用）→ 把必要逻辑迁进 owner → 删模块 → **同 PR 收缩基线** → 行为级测试全绿 → 门禁与 CI。
- 不删除仍有行为契约的测试；只把断言从"旧对象存在/隐藏"改成"新 owner 的行为"。
- `docs/architecture.md` 描述的隐藏兼容对象（hidden widget/frame/layout）一律按债务处理，不视为扩展方式。

## 3. 执行批次

| 批次 | 范围 | 行数 | 状态 |
|---|---|---|---|
| Wave 0 | 死代码：`mobile_upload_dialog.py`、`buyer_warning_readability.py`，测试重定向 | −318 行 | PR #202（CI 绿） |
| Wave 1 | 小契约：`review_legacy_contract.py`、`settings_legacy_contract.py`、`ui_visibility_contracts.py`；逻辑迁进 `InvoiceDetailPanel` / `app.py`；基线 14→11、3→2 | ~268 行 | 本 PR |
| Wave 2 | `settings_dialog.py` 3,901 行退休 + 9 个测试文件迁到在窗设置页 | ~4,000 行 | 待做（最大单笔） |
| Wave 3 | 基线/修复 11 个模块，分 3 个 PR（小→大）：`design_baseline_styles`、`business_pages_baseline`、`review_workspace_baseline`、`review_baseline_pipeline`、`review_feedback_fixes`、`review_toolbar_filter_fixes`、`review_settings_issue_fixes`、`settings_baseline`、`settings_pages_baseline`、`design_v1_review_task_closure`、`hci_v1_closure`（+`hci_v1`） | ~5,135 | 待做（每 PR 收缩基线） |
| Wave 4 | 重复 token 层收敛：`styles.py` 第二套 token → `design_tokens.py` 单一来源；QSS 模板化 | 影响 ~682 处 hex 字面量 | 待做（同时是界面 P1-21 前置） |

Wave 4 完成后，按 `docs/ui-apple-hig-review.md` 分 3 批做界面修复（P0 无障碍/布局 → P1 组件与设计系统 → P2 平台化）。

## 4. 每批验收

1. `python scripts/check_architecture_policy.py` 基线与实际一致（只减不增）。
2. 模块隔离回归：受影响模块 + `tests/test_gui_module_boundaries.py`、`tests/test_architecture_policy.py`、`tests/test_gui_legacy_patch_governance.py`。
3. 门禁：`check_repo_privacy.py`、`check_public_export.py .`、`compileall`、`git diff --check`、行尾守卫（raw vs `--ignore-space-at-eol` numstat 一致）。
4. CI 三个 Windows 分片全绿；PR 描述写明删除行数与基线变化。

## 5. 本轮附带的仓库清理（2026-10-31）

- 本地 `master` 曾分叉为 8 个重复 merge 提交；已证明 origin 包含其全部内容（trial-merge 内容 diff 为空），备份 ref 已删除。
- 22 个本地分支（17 个已合并 + 5 个被 origin 取代/内容相同）与 2 个 stash（内容均已在 origin）已清理；仅保留 `master` 与进行中的 PR 分支。
- 结论：分叉**没有可吸纳的独有功能**；唯一有效未合并工作为 PR #201（凭据/导出边界修复）。
