# GUI 历史补丁模块治理

更新日期：2026-10-09

当前 `scripts/invoice_fetch/gui/` 共 85 个 Python 模块，其中以下 7 个文件属于历史 `*_fixes.py` / `*_baseline.py` 补丁模块：

- `business_pages_baseline.py`
- `review_feedback_fixes.py`
- `review_settings_issue_fixes.py`
- `review_toolbar_filter_fixes.py`
- `review_workspace_baseline.py`
- `settings_baseline.py`
- `settings_pages_baseline.py`

这 7 个文件构成冻结清单。新增产品功能不得创建新的 `*_fixes.py` 或 `*_baseline.py` 文件，也不得把既有补丁文件复制到其他页面或子包。可复用 UI 放入标准组件模块（优先 `gui/ui/components/`）；页面专属组装留在所属页面或领域模块。

冻结不代表这些补丁流水线已经退役。未来可逐步迁移或删除既有实现，但迁移必须同时更新清单、移除源补丁，并由用户行为回归覆盖。允许必要的窄范围缺陷修复；禁止借缺陷修复之名继续扩展旧补丁模块的职责。

`tests/test_gui_legacy_patch_governance.py` 校验清单必须保持不变。每次有意退役一个补丁模块时，需在同一变更中更新该测试与本文；清单不得增长。
