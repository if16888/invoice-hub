# PR: refactor(ui): unify UI kit on Design v1 tokens and polish accessibility

**分支**：`ui/design-v1-polish` → `master`

## 背景

`docs/design/DESIGN_V1_TOKEN_MIGRATION_CHECKLIST.md` 的迁移尚未完成，当前界面层存在三套互相冲突的设计令牌，且大量内联硬编码样式散落在业务代码中。本 PR 完成 UI Kit 层面的统一，并顺手修复一批可用性问题。

## 改动内容

### 1. 令牌统一（P0）
- `ui/theme.py` 的核心颜色、字阶、圆角、控件高度改为从 `design_tokens.py`（Design v1 权威）派生，不再重复定义竞争值：
  - 页面底 `#F6F8FB` → `#F7F8FA`，正文 `#172033` → `#182230`
  - 次要文本 `#667085` → `#475467`（text_secondary），弱提示 `#98A2B3` → `#667085`（muted，**对比度从约 2.9:1 提升到约 4.8:1**，满足 WCAG AA）
  - 控件高度 36 → 34，卡片圆角 12 → 10，与 v1 度量对齐
  - 语义色对齐 v1：success `#16803C`、warning `#B54708`、danger `#B42318` 及对应 surface
- `app.py` 的 `REVIEW_STATUS_BADGES` / `DATA_STATUS_BADGES` 调色板改为从 v1 语义色派生
- `settings_dialog.py` 状态红 `#EF4444` → v1 danger；`preview_mixin.py`、`preview_toolbar.py`、`review_toolbar_filter_fixes.py` 的残留字面量同步迁移

### 2. 内联样式治理（P0）
- `app.py` 中 20+ 处 `setStyleSheet` 硬编码颜色迁移到集中 QSS 的语义标签角色：`role="hint" / "secondary" / "caption" / "status" / "emphasis" / "strong" / "guide"`
- 组件去硬编码：`SectionHeader`（标题/副标题改走 QSS class）、`FormField`（label/hint 改走 QSS class）、`PreviewToolbar`（f-string 引用 Theme）

### 3. 可用性修复（P1）
- **键盘焦点环**：按钮、侧边导航、Tab、StatCard、预览工具条补充 `:focus` 样式（此前只有输入框有焦点样式）
- **StatCard 可键盘操作**：补 `StrongFocus`，Enter/Space 激活此前无法生效
- **导航选中态文字跳动**：`border-left: 3px` 增加 padding 补偿
- **StatCard 圆角**：写死的 10px 改为卡片圆角令牌
- **表格**：补 hover 行高亮与斑马纹底色（`alternate-background-color`）
- **滚动条**：6px → 8px，增加横向滚动条样式与滑块悬停态
- **输入框焦点**：1.5px 描边 → 2px + padding 补偿，视觉更稳定

## 测试

- 更新契约测试：`test_ui_kit.py`（BG_PAGE 期望）、`test_gui_column_filters.py`（发票号弱提示色期望 `#94a3b8` → `#667085`）
- 全量逐文件运行：`66/67` 个测试文件通过；其余失败均在未改动的 master 上复现，与本 PR 无关：
  - `test_claim_groups.py` 3 个（Windows 路径分隔符 / Windows 控制台 / GUI prompt，平台相关）
  - `test_ihds09.py` 3 个（offscreen 字体度量下的几何裁剪，master 同样失败）
  - `test_startup_probe_and_packaging.py` 1 个（依赖 `powershell.exe`，Windows-only）

## 未纳入（建议后续 PR）

- `styles.py` 遗留模块的整体下线（运行时已被 `apply_legacy_color_tokens` + `_purge_obsolete_literals` 覆盖，建议按 checklist 渐进迁移）
- 深色模式（令牌已就绪，加一套 dark palette 即可）
- Windows 100%/125%/150% 缩放的实机物理审查（checklist 要求）

## 本地验证方式

```powershell
pip install -r requirements.txt -r requirements-desktop.txt
python -m pytest tests/test_ui_kit.py tests/test_design_token_authority.py tests/test_design_baseline_tokens.py -q
python -m scripts.invoice_fetch desktop
```
