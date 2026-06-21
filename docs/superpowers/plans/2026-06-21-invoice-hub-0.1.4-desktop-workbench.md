# Invoice Hub 0.1.4 Main Review Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the 1920×1080 “top records, bottom preview, fixed right detail” review workbench with reusable desktop components, automatic incremental loading, synchronized selection, compact shortcuts, and no pagination.

**Architecture:** Preserve `InvoiceReviewApp` as the orchestration boundary, the existing vertical `left_splitter`, `PreviewMixin`, and `InvoiceDetailPanel`. Add small pure helpers for layout metrics, query-window state, and shortcut routing; keep database writes and review transactions in `InvoiceReviewApp`. Replace the explicit first-100 “加载全部” flow with automatic offset batches while retaining full status counts and the existing advanced-filter semantics.

**Tech Stack:** Python 3.11+, PySide6 Qt Widgets/QSS, SQLite through `InvoiceDB`, `unittest`.

---

## Scope and safety constraints

- Implement only the 0.1.4 main review workbench and reusable components it actually uses.
- Do not redesign mailbox settings, OAuth2, mobile-upload service behavior, parsing, deduplication, export, claim-group rules, or secret handling.
- Preserve public GUI attributes already referenced by tests unless a task explicitly migrates the tests in the same commit.
- Preserve `config.email_accounts`, `mailbox_key`, authorization-code privacy, source-file, soft-delete, and evidence-link semantics.
- Do not stage or modify the unrelated user-owned `tests/test_startup_probe_and_packaging.py` change.
- Use a dedicated worktree when executing this plan.

## File map

| File | Responsibility in this plan |
|---|---|
| `scripts/invoice_fetch/gui/workbench_layout.py` | Pure responsive metrics and splitter clamping |
| `scripts/invoice_fetch/gui/workbench_state.py` | Incremental-window and keyboard-focus decisions |
| `scripts/invoice_fetch/gui/ui_components.py` | Reusable compact cards, shortcut disclosure, action buttons |
| `scripts/invoice_fetch/gui/styles.py` | Shared tokens and component QSS |
| `scripts/invoice_fetch/db.py` | Stable offset query support |
| `scripts/invoice_fetch/gui/column_filters.py` | Separate visible columns from advanced filter definitions |
| `scripts/invoice_fetch/gui/app.py` | Main shell, layout, loading, selection synchronization, shortcuts |
| `scripts/invoice_fetch/gui/preview_mixin.py` | Preview toolbar, thumbnail rail, rotation, focus mode |
| `scripts/invoice_fetch/gui/invoice_detail_panel.py` | Fixed summary/actions and scrollable tabs |
| `tests/test_workbench_layout.py` | Responsive layout and splitter persistence |
| `tests/test_workbench_state.py` | Pure incremental/focus state tests |
| `tests/test_gui_column_filters.py` | Visible-column and advanced-filter compatibility |
| `tests/test_preview_workbench_ui.py` | Toolbar, thumbnails, rotation, focus mode |
| `tests/test_detail_panel_ui.py` | Fixed detail header and tab contracts |
| `tests/test_claim_groups.py` | Existing integrated workbench and review regressions |

## Task 1: Freeze the current behavior and responsive metrics

**Files:**
- Create: `scripts/invoice_fetch/gui/workbench_layout.py`
- Create: `tests/test_workbench_layout.py`

- [ ] **Step 1: Write failing pure metric tests**

```python
from scripts.invoice_fetch.gui.workbench_layout import metrics_for_size, clamp_vertical_split


def test_1920_layout_uses_full_density():
    metrics = metrics_for_size(1920, 1080)
    assert metrics.nav_width == 208
    assert metrics.detail_width == 444
    assert metrics.record_height == 340
    assert metrics.thumbnail_width == 104
    assert metrics.compact is False


def test_1366_layout_collapses_navigation():
    metrics = metrics_for_size(1366, 768)
    assert metrics.nav_collapsed is True
    assert 360 <= metrics.detail_width <= 380
    assert metrics.record_height == 300


def test_splitter_restore_is_clamped():
    assert clamp_vertical_split(900, 50, record_min=280, preview_min=300) == (280, 620)
    assert clamp_vertical_split(900, 850, record_min=280, preview_min=300) == (600, 300)
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `python -m unittest tests.test_workbench_layout -v`

Expected: FAIL with `ModuleNotFoundError: scripts.invoice_fetch.gui.workbench_layout`.

- [ ] **Step 3: Implement immutable metrics and splitter clamping**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkbenchMetrics:
    nav_width: int
    nav_collapsed: bool
    detail_width: int
    record_height: int
    thumbnail_width: int
    compact: bool


def metrics_for_size(width: int, height: int) -> WorkbenchMetrics:
    if width <= 1366 or height <= 768:
        return WorkbenchMetrics(56, True, 370, 300, 96, True)
    if width <= 1440 or height <= 900:
        return WorkbenchMetrics(208, False, 390, 320, 96, True)
    return WorkbenchMetrics(208, False, 444, 340, 104, False)


def clamp_vertical_split(total: int, record: int, *, record_min: int, preview_min: int) -> tuple[int, int]:
    record = max(record_min, min(record, total - preview_min))
    return record, total - record
```

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_workbench_layout -v`

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```text
git add scripts/invoice_fetch/gui/workbench_layout.py tests/test_workbench_layout.py
git commit -m "test: define desktop workbench metrics"
```

## Task 2: Add reusable compact workbench components

**Files:**
- Modify: `scripts/invoice_fetch/gui/ui_components.py`
- Modify: `scripts/invoice_fetch/gui/styles.py`
- Create: `tests/test_ui_components.py`

- [ ] **Step 1: Add failing component-contract tests**

```python
def test_stat_card_exposes_filter_state(qapp):
    card = CompactStatCard("待审核", "117", state="warning")
    card.set_selected(True)
    assert card.property("selected") is True
    assert card.objectName() == "CompactStatCard"


def test_shortcut_disclosure_defaults_to_core_actions(qapp):
    panel = ShortcutDisclosure()
    assert panel.is_expanded() is False
    assert panel.visible_shortcuts() == ("Enter", "Del", "Ctrl+E")
```

- [ ] **Step 2: Verify failure**

Run: `python -m unittest tests.test_ui_components -v`

Expected: FAIL because `CompactStatCard` and `ShortcutDisclosure` do not exist.

- [ ] **Step 3: Implement the reusable interfaces**

Add `CompactStatCard(title, value, state)`, `set_value()`, `set_selected()`, and `clicked`; add `ShortcutDisclosure.set_expanded()`, `is_expanded()`, and `visible_shortcuts()`. Components emit intent only and never query the database.

```python
CORE_SHORTCUTS = (("Enter", "通过"), ("Del", "忽略"), ("Ctrl+E", "异常"))
SECONDARY_SHORTCUTS = (
    ("↑ / ↓", "切换发票"), ("Ctrl+F", "搜索"), ("F11", "预览全屏"),
    ("Ctrl+I", "导入"), ("Ctrl+U", "扫码上传"),
    ("Ctrl+M", "邮箱同步"), ("Ctrl+R", "刷新"),
)
```

Use semantic properties (`state`, `selected`, `expanded`) and QSS selectors; do not use per-widget inline style sheets.

- [ ] **Step 4: Run component and style tests**

Run: `python -m unittest tests.test_ui_components tests.test_ui_style_architecture -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```text
git add scripts/invoice_fetch/gui/ui_components.py scripts/invoice_fetch/gui/styles.py tests/test_ui_components.py
git commit -m "feat: add reusable workbench components"
```

## Task 3: Recompose the 1920×1080 shell around the existing splitters

**Files:**
- Modify: `scripts/invoice_fetch/gui/app.py`
- Modify: `tests/test_workbench_layout.py`
- Modify: `tests/test_claim_groups.py`

- [ ] **Step 1: Add failing integration assertions**

Create a window with a temporary database, resize it to 1920×1080, process events, then assert:

```python
assert window.main_splitter.orientation() == Qt.Horizontal
assert window.left_splitter.orientation() == Qt.Vertical
assert window.left_splitter.widget(0) is window.left_upper_widget
assert window.left_splitter.widget(1) is window.preview_panel
assert window._detail_panel.minimumWidth() >= 420
assert window.table.horizontalHeader().isVisible()
```

Also retain existing assertions that every `main_splitter` and `left_splitter` size remains greater than zero when diagnostics expand/collapse.

- [ ] **Step 2: Run targeted tests and observe the width/default failures**

Run: `python -m unittest tests.test_workbench_layout tests.test_claim_groups -v`

Expected: new workbench layout assertions FAIL; existing claim tests remain green.

- [ ] **Step 3: Apply metrics without replacing the existing hierarchy**

In `InvoiceReviewApp._init_ui()`:

```python
metrics = metrics_for_size(self.width(), self.height())
self._detail_panel.setMinimumWidth(360 if metrics.compact else 420)
self._detail_panel.setMaximumWidth(468)
self.main_splitter.setStretchFactor(0, 1)
self.main_splitter.setStretchFactor(1, 0)
self.left_splitter.setStretchFactor(0, 0)
self.left_splitter.setStretchFactor(1, 1)
self.left_splitter.setSizes([metrics.record_height, max(300, self.height() - metrics.record_height)])
```

Keep the fixed right summary/actions outside the detail scroll area; “fixed” means the panel remains visible and its header/actions do not scroll, not that all detail fields are non-scrollable.

- [ ] **Step 4: Add splitter preference persistence**

Use `QSettings("InvoiceHub", "InvoiceHub")` with keys `workbench/main_splitter`, `workbench/left_splitter`, and `workbench/shortcut_help_expanded`. Restore only after widgets have valid sizes; clamp restored vertical sizes through `clamp_vertical_split`. Save from `closeEvent()` and debounced `splitterMoved` handlers.

- [ ] **Step 5: Run targeted tests**

Run: `python -m unittest tests.test_workbench_layout tests.test_claim_groups -v`

Expected: PASS, including restored-state clamp and diagnostics expansion tests.

- [ ] **Step 6: Commit**

```text
git add scripts/invoice_fetch/gui/app.py tests/test_workbench_layout.py tests/test_claim_groups.py
git commit -m "feat: compose vertical review workbench"
```

## Task 4: Separate visible invoice columns from advanced filters

**Files:**
- Modify: `scripts/invoice_fetch/gui/column_filters.py`
- Modify: `scripts/invoice_fetch/gui/app.py`
- Modify: `tests/test_gui_column_filters.py`

- [ ] **Step 1: Add failing column-contract tests**

```python
assert tuple(key for key, _label in VISIBLE_COLUMN_DEFINITIONS) == (
    "review_status", "expense_date", "total_amount", "seller_name", "invoice_number"
)
assert "status" in COLUMN_KEYS          # existing completeness filter
assert COLUMN_LABELS["status"] == "完整性"
```

At window level assert the five visible headers are `状态`, `费用日期`, `金额`, `销售方`, `发票号`, while filter menus can still address completeness, category, source, and claim group.

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.test_gui_column_filters -v`

Expected: FAIL because visible and filter definitions are currently the same eight-column tuple.

- [ ] **Step 3: Introduce an explicit visible definition**

```python
VISIBLE_COLUMN_DEFINITIONS = (
    ("review_status", "状态"),
    ("expense_date", "费用日期"),
    ("total_amount", "金额"),
    ("seller_name", "销售方"),
    ("invoice_number", "发票号"),
)
```

Keep `COLUMN_DEFINITIONS`, `COLUMN_KEYS`, and existing filter specs unchanged. In `app.py`, render review status from `invoice["review_status"] or TO_REVIEW`; retain completeness value getters exclusively for advanced filtering. Add ellipsis/tooltip for seller and invoice number and right-align amount.

- [ ] **Step 4: Replace footer controls with the summary contract**

Remove the pagination/load-all visual slot and update the footer text through one method:

```python
def _update_record_summary(self) -> None:
    selected = len(self.table.selectionModel().selectedRows())
    amount = sum(Decimal(str(inv.get("total_amount") or 0)) for inv in self._selected_invoices())
    self.lbl_record_summary.setText(
        f"共 {self._matching_invoice_count} 张    已选 {selected} 张    合计 ¥{amount:.2f}"
    )
```

- [ ] **Step 5: Run filter tests**

Run: `python -m unittest tests.test_gui_column_filters -v`

Expected: PASS; completeness remains an advanced filter and no visible column reuses that semantic key.

- [ ] **Step 6: Commit**

```text
git add scripts/invoice_fetch/gui/column_filters.py scripts/invoice_fetch/gui/app.py tests/test_gui_column_filters.py
git commit -m "feat: simplify invoice record columns"
```

## Task 5: Replace “load all” with automatic incremental loading

**Files:**
- Modify: `scripts/invoice_fetch/db.py`
- Create: `scripts/invoice_fetch/gui/workbench_state.py`
- Create: `tests/test_workbench_state.py`
- Modify: `tests/test_claim_groups.py`
- Modify: `tests/test_gui_column_filters.py`

- [ ] **Step 1: Add failing database window tests**

```python
rows = db.list_invoices(limit=100, offset=100)
assert len(rows) == 100
assert rows[0]["id"] != db.list_invoices(limit=100, offset=0)[0]["id"]
with self.assertRaises(ValueError):
    db.list_invoices(limit=100, offset=-1)
```

- [ ] **Step 2: Implement stable offset support**

Change the signature to:

```python
def list_invoices(
    self,
    status: str | None = None,
    limit: int | None = None,
    include_deleted: bool = False,
    offset: int = 0,
) -> list[dict]:
```

Validate `offset >= 0`. Preserve `ORDER BY i.expense_date DESC, i.id DESC`; when `limit` is present append `LIMIT ? OFFSET ?`. Reject a non-zero offset without a limit so callers cannot accidentally hydrate the remainder.

- [ ] **Step 3: Add failing query-window tests**

```python
state = IncrementalWindow(batch_size=100)
assert state.next_query() == (100, 0)
state.accept_batch(100, total=303)
assert state.next_query() == (100, 100)
state.accept_batch(3, total=303)
assert state.has_more is False
```

- [ ] **Step 4: Implement `IncrementalWindow`**

The class owns `batch_size`, `offset`, `total`, `loading`, `has_more`, `generation`; `reset()` increments generation so stale asynchronous results can be ignored. It contains no Qt or database imports.

- [ ] **Step 5: Integrate automatic loading in `InvoiceReviewApp`**

- Delete `_load_all_invoices_clicked`, `_limited_first_load_active`, `_limited_first_load_total`, and `btn_load_all` UI creation.
- Connect `table.verticalScrollBar().valueChanged` to `_maybe_load_next_invoice_batch`.
- Trigger the next batch when `maximum - value <= max(3 * table.verticalHeader().defaultSectionSize(), 80)`.
- Append rows without calling `setRowCount(0)` and preserve selected invoice ID and scrollbar value.
- Keep full status counts from `count_invoices_for_status()`.
- Reset the window on search, status, deleted toggle, sort, or advanced-filter changes.
- For active client-side advanced filters, keep the existing full-source path in 0.1.4, but render it in 100-row UI batches; document this bounded compatibility path and do not reintroduce page controls.

- [ ] **Step 6: Add integrated regressions**

Replace tests that expect `btn_load_all` with tests asserting:

```python
assert window.table.rowCount() == 100
scrollbar.setValue(scrollbar.maximum())
QApplication.processEvents()
assert window.table.rowCount() == 200
assert window._matching_invoice_count == 303
assert not hasattr(window, "btn_load_all")
```

Also test batch failure leaves existing rows intact and exposes a retry action in the list footer.

- [ ] **Step 7: Run data and GUI tests**

Run: `python -m unittest tests.test_workbench_state tests.test_gui_column_filters tests.test_claim_groups -v`

Expected: PASS; default load never calls `list_invoices(limit=None)` for 1000 records.

- [ ] **Step 8: Commit**

```text
git add scripts/invoice_fetch/db.py scripts/invoice_fetch/gui/workbench_state.py scripts/invoice_fetch/gui/app.py tests/test_workbench_state.py tests/test_gui_column_filters.py tests/test_claim_groups.py
git commit -m "feat: load invoice records continuously"
```

## Task 6: Make selection a single synchronized view state

**Files:**
- Modify: `scripts/invoice_fetch/gui/app.py`
- Modify: `tests/test_claim_groups.py`

- [ ] **Step 1: Add failing selection synchronization tests**

Select an invoice by ID and assert the row, `current_invoice`, preview document, and detail summary all change together. Append another batch and assert the selected invoice ID remains unchanged. Filter the selected invoice out and assert the first visible record becomes current.

- [ ] **Step 2: Introduce one selection dispatcher**

```python
def _select_invoice_by_id(self, invoice_id: int | None, *, fallback_first: bool = True) -> None:
    invoice = self._invoice_by_id(invoice_id)
    if invoice is None and fallback_first and self.invoices_list:
        invoice = self.invoices_list[0]
    self.current_invoice = invoice
    self._sync_table_selection(invoice)
    self._sync_preview(invoice)
    self._detail_panel.set_invoice(invoice)
    self._update_record_summary()
```

Route table selection, filter reset, batch append, review auto-advance, and upload refresh through this dispatcher. Keep signal blockers around programmatic table selection to prevent recursion.

- [ ] **Step 3: Preserve multi-select semantics**

When multiple rows are selected, clear single-record detail/preview and show batch summary; do not leave stale data from the previous current invoice. Do not add `Space` selection behavior.

- [ ] **Step 4: Run integrated tests**

Run: `python -m unittest tests.test_claim_groups -v`

Expected: PASS for selection, preview, detail, review auto-advance, and claim-group regressions.

- [ ] **Step 5: Commit**

```text
git add scripts/invoice_fetch/gui/app.py tests/test_claim_groups.py
git commit -m "refactor: synchronize workbench selection"
```

## Task 7: Rebuild the preview workbench controls

**Files:**
- Modify: `scripts/invoice_fetch/gui/preview_mixin.py`
- Modify: `scripts/invoice_fetch/gui/app.py`
- Create: `tests/test_preview_workbench_ui.py`
- Modify: `tests/test_ui_preview_helpers.py`
- Modify: `tests/test_preview_pdf_nav_log_001.py`

- [ ] **Step 1: Add failing toolbar and thumbnail tests**

Assert the visible action order is:

```python
(
    "zoom_out", "zoom_100", "zoom_in", "fit_width", "fit_page",
    "rotate_left", "rotate_right", "download", "print", "focus_mode",
)
```

Provide two preview documents, click thumbnail 2, and assert `current_preview_index == 1` and the selected thumbnail property is true.

- [ ] **Step 2: Add failing focus-mode tests**

Enter preview focus mode and assert current invoice/document indices are preserved, the preview is reparented into a dedicated overlay widget, and `Esc` restores it to the original splitter position. Do not call `QMainWindow.showFullScreen()`.

- [ ] **Step 3: Implement the fixed toolbar and 96–120 px thumbnail rail**

Add focused helpers with these exact contracts:

- `_build_preview_toolbar() -> QWidget` creates the ten actions in the tested order and stores them in `self.preview_actions` by stable key.
- `_refresh_preview_thumbnails() -> None` rebuilds the rail from `current_preview_docs`, applies `selected=True` only to `current_preview_index`, and shows the add-attachment control last.
- `_select_preview_doc(index: int) -> None` bounds-checks the index, updates `current_preview_index`, refreshes the rail, and calls the existing document renderer once.
- `_rotate_preview(degrees: int) -> None` accepts only `-90` or `90`, updates normalized rotation modulo 360, and rerenders the current document.
- `_toggle_preview_focus_mode() -> None` delegates to enter/exit helpers while preserving invoice ID, document index, splitter sizes, and original parent/layout index.

Keep existing PDF page navigation available inside the document view without adding it to the primary toolbar. Wheel scrolls the document; `Ctrl+wheel` changes zoom. Double-clicking the canvas toggles focus mode.

- [ ] **Step 4: Preserve disabled-state reasons**

Download, print, rotation, and zoom actions must be disabled with a tooltip when the current file type or missing-file state does not support them. Keep evidence linkage and external-open behavior reachable from the attachment context menu.

- [ ] **Step 5: Run preview tests**

Run: `python -m unittest tests.test_preview_workbench_ui tests.test_ui_preview_helpers tests.test_preview_pdf_nav_log_001 -v`

Expected: PASS for PDF/image navigation, thumbnails, rotation state, and focus-mode restoration.

- [ ] **Step 6: Commit**

```text
git add scripts/invoice_fetch/gui/preview_mixin.py scripts/invoice_fetch/gui/app.py tests/test_preview_workbench_ui.py tests/test_ui_preview_helpers.py tests/test_preview_pdf_nav_log_001.py
git commit -m "feat: streamline invoice preview workbench"
```

## Task 8: Fix the review summary and actions above scrollable detail tabs

**Files:**
- Modify: `scripts/invoice_fetch/gui/invoice_detail_panel.py`
- Modify: `scripts/invoice_fetch/gui/styles.py`
- Modify: `tests/test_detail_panel_ui.py`
- Modify: `tests/test_claim_groups.py`

- [ ] **Step 1: Add failing hierarchy tests**

Assert amount, status, invoice type, date, invoice number, seller, risk notice, and `btn_app`/`btn_ign`/`btn_err` are ancestors of the fixed header container, not the tab scroll viewport. Assert button text includes `Enter`, `Del`, and `Ctrl+E` as secondary labels.

- [ ] **Step 2: Recompose without changing callbacks**

Keep `InvoiceDetailCallbacks` intact. Build:

```text
InvoiceDetailPanel
├── fixed_summary
├── fixed_risk_notice
├── fixed_review_actions
└── detail_tabs
    ├── 基本信息
    ├── 报销信息
    ├── 关联合同 (only when a real capability is supplied)
    └── 操作记录 (only real traceable events)
```

Do not render empty contract/history placeholders. Preserve inline note editing, compact claim row, dirty-state protection, attachments, save behavior, and detail vertical scrolling inside each populated tab.

- [ ] **Step 3: Keep action positions stable across states**

Risk-empty, risk-warning, disabled, saving, success, and error states must not move or resize the three review buttons. `mark error` still requires a reason; approve-next still validates and saves dirty fields before changing status.

- [ ] **Step 4: Run detail and workflow tests**

Run: `python -m unittest tests.test_detail_panel_ui tests.test_claim_groups -v`

Expected: PASS, including note, claim-group, attachment, dirty-state, and review transaction tests.

- [ ] **Step 5: Commit**

```text
git add scripts/invoice_fetch/gui/invoice_detail_panel.py scripts/invoice_fetch/gui/styles.py tests/test_detail_panel_ui.py tests/test_claim_groups.py
git commit -m "feat: fix review actions above detail tabs"
```

## Task 9: Centralize compact keyboard routing and focus priority

**Files:**
- Modify: `scripts/invoice_fetch/gui/workbench_state.py`
- Modify: `scripts/invoice_fetch/gui/app.py`
- Modify: `scripts/invoice_fetch/gui/preview_mixin.py`
- Modify: `tests/test_workbench_state.py`
- Modify: `tests/test_detail_panel_ui.py`
- Modify: `tests/test_preview_workbench_ui.py`

- [ ] **Step 1: Add failing focus-classification tests**

```python
assert is_keyboard_input_target(QLineEdit()) is True
assert is_keyboard_input_target(QTextEdit()) is True
combo = QComboBox(); combo.setEditable(True)
assert is_keyboard_input_target(combo) is True
assert is_keyboard_input_target(QTableWidget()) is False
```

- [ ] **Step 2: Implement one routing guard**

`is_keyboard_input_target(widget)` walks parents and recognizes line edits, text edits, plain-text edits, spin/date controls, and editable combos. `InvoiceReviewApp._invoke_workbench_action(action)` returns without executing when a modal widget exists or the focused editor owns the key.

- [ ] **Step 3: Register only the approved shortcuts**

```python
bindings = {
    Qt.Key_Up: lambda: self._move_invoice_selection(-1),
    Qt.Key_Down: lambda: self._move_invoice_selection(1),
    Qt.Key_Return: lambda: self._set_selected_status(APPROVED),
    Qt.Key_Delete: lambda: self._set_selected_status(IGNORED),
    QKeySequence("Ctrl+E"): lambda: self._set_selected_status(ERROR),
    QKeySequence("Ctrl+F"): self.txt_search.setFocus,
    QKeySequence("F11"): self._toggle_preview_focus_mode,
    QKeySequence("Ctrl+I"): self._open_import,
    QKeySequence("Ctrl+U"): self._open_mobile_upload,
    QKeySequence("Ctrl+M"): self._sync_mailboxes,
    QKeySequence("Ctrl+R"): self._load_invoices,
}
```

Before editing, map `_open_import`, `_open_mobile_upload`, `_sync_mailboxes`, and `_load_invoices` to the existing callback methods in `InvoiceReviewApp`; bind directly to those methods and do not create duplicate business entry points. Register Return and keypad Enter. `Esc` resolves in order: modal/dialog, preview focus mode, transient panel. Do not register `Space`, `J/K`, or old `Alt+A/I/E` aliases.

- [ ] **Step 4: Test focus conflicts**

Verify `Enter`, `Delete`, arrows, and `Ctrl+E` do not trigger review/navigation inside detail inputs, search, editable combos, or modal dialogs. In preview focus mode retain Enter/Delete/Ctrl+E/F11/Esc; arrows remain owned by PDF navigation.

- [ ] **Step 5: Run shortcut tests**

Run: `python -m unittest tests.test_workbench_state tests.test_detail_panel_ui tests.test_preview_workbench_ui -v`

Expected: PASS with no review callback invoked from an editing widget or modal dialog.

- [ ] **Step 6: Commit**

```text
git add scripts/invoice_fetch/gui/workbench_state.py scripts/invoice_fetch/gui/app.py scripts/invoice_fetch/gui/preview_mixin.py tests/test_workbench_state.py tests/test_detail_panel_ui.py tests/test_preview_workbench_ui.py
git commit -m "feat: add focused review shortcuts"
```

## Task 10: Integrate compact status filtering and shortcut disclosure

**Files:**
- Modify: `scripts/invoice_fetch/gui/app.py`
- Modify: `scripts/invoice_fetch/gui/styles.py`
- Modify: `tests/test_workbench_layout.py`
- Modify: `tests/test_gui_column_filters.py`

- [ ] **Step 1: Add failing interaction tests**

Assert five compact cards fit within 88 px at 1920×1080, selecting “待审核” immediately resets incremental loading and filters the records, and counts still represent the full database. Assert shortcut help defaults collapsed, expanding it does not resize the center workbench, and its state restores through settings.

- [ ] **Step 2: Replace oversized status controls with `CompactStatCard`**

Keep existing status constants and callbacks. Cards display only icon, name, and number; the selected state is semantic and keyboard-focusable. Put filter and refresh in the record title bar; do not duplicate the global search field.

- [ ] **Step 3: Add the left-bottom disclosure**

Place `ShortcutDisclosure` beside the existing sidebar collapse action. Default summary contains only Enter/Del/Ctrl+E; the expanded content includes arrows, search, focus mode, import, upload, mail sync, and refresh.

- [ ] **Step 4: Run layout/filter tests**

Run: `python -m unittest tests.test_workbench_layout tests.test_gui_column_filters -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```text
git add scripts/invoice_fetch/gui/app.py scripts/invoice_fetch/gui/styles.py tests/test_workbench_layout.py tests/test_gui_column_filters.py
git commit -m "feat: compact workbench filters and help"
```

## Task 11: Responsive, performance, and release verification

**Files:**
- Modify: `tests/test_workbench_layout.py`
- Modify: `tests/test_claim_groups.py`

- [ ] **Step 1: Add final acceptance cases**

Cover 1920×1080, 1440×900, 1366×768, and 1280×720. Assert no horizontal workbench scrollbar, detail and preview minimums remain usable, splitter children remain non-zero, and 1366 defaults to collapsed navigation.

- [ ] **Step 2: Add the 300+ record acceptance case**

Seed 303 invoices. Verify fixed headers, 100→200→303 automatic batches, selected ID preservation, full count 303, no pagination/load-all controls, and record footer `共 303 张`.

- [ ] **Step 3: Run focused GUI suites**

Run:

```text
python -m unittest tests.test_workbench_layout tests.test_workbench_state tests.test_ui_components tests.test_gui_column_filters tests.test_preview_workbench_ui tests.test_ui_preview_helpers tests.test_preview_pdf_nav_log_001 tests.test_detail_panel_ui tests.test_claim_groups -v
```

Expected: all focused tests PASS.

- [ ] **Step 4: Run repository verification**

Run:

```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall scripts tests
python scripts/check_public_export.py
git diff --check
```

Expected: all tests PASS, compileall succeeds, public-export check succeeds, and `git diff --check` prints no errors. If tests recreate `runtime/`, remove only that generated directory after verifying it is inside this worktree.

- [ ] **Step 5: Perform manual desktop acceptance**

At 1920×1080 verify 8–10 rows, readable preview, fixed review actions, wheel/keyboard behavior, splitter persistence, risk states, and button muscle-memory positions. Repeat the main approve/ignore/error flow at 1440×900 and 1366×768.

- [ ] **Step 6: Commit release verification updates**

```text
git add tests/test_workbench_layout.py tests/test_claim_groups.py
git commit -m "test: verify desktop review workbench"
```

## Execution checkpoints

1. Tasks 1–3: reusable foundation and correct vertical shell.
2. Tasks 4–6: record semantics, continuous data, synchronized selection.
3. Tasks 7–10: preview, fixed detail, keyboard, compact controls.
4. Task 11: full verification and manual acceptance.

Do not start a later checkpoint while the focused tests for the current checkpoint are failing.

## Design coverage matrix

| Design requirement | Task |
|---|---:|
| 1920×1080 baseline and smaller-size degradation | 1, 3, 11 |
| Reusable components | 1, 2, 10 |
| Top records / bottom preview / fixed right detail | 3, 7, 8 |
| 固定表头 and five visible columns | 4 |
| No pagination; continuous 300+ loading | 5, 11 |
| Full counts and advanced-filter compatibility | 4, 5, 10 |
| List/preview/detail synchronization | 6 |
| Draggable persisted splitter | 1, 3 |
| Simplified preview toolbar and 缩略图 rail | 7 |
| Local preview full screen | 7, 9 |
| Stable review actions and detail tabs | 8 |
| Reduced 快捷键 and focus safety | 9, 10 |
| Collapsible shortcut help | 2, 10 |

## Model allocation during execution

- Low-cost model: Tasks 1, 2, pure tests in 4/5/9, documentation, acceptance recording.
- Strong model: Tasks 3, 5 integration, 6, 7 focus mode, 8 review transactions, 9 routing integration, final review.
- Every worker receives only its task, exact files, existing dirty-worktree warning, and required focused test command.
