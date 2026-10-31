# Invoice Hub 界面深度盘点（Apple HIG / macOS 桌面基准）

- **基线**：`master` @ `6c88934`（本地已更新到手；上次的 `fix/credentials-and-export-edges` PR #201 尚未合入，故不在本次界面范围内）
- **方法**：真实界面截图（隐藏窗口渲染、合成数据，20 张）+ 3 路并行审计（设计系统量化 / 审查工作台 / 详情·预览·设置·对话框）
- **截图目录**：`%TEMP%\ih-ui-review\shots\`（复现脚本：`%TEMP%\ih-ui-review\capture_v2.py`，重跑可生成同一套截图做前后对比）
- **结论**：基础不差——已有设计 token、蓝色单一强调色（canonical 层）、190ms 合规动效、SVG currentColor 图标、设置页 master-detail、响应式侧栏/详情折叠；但"卡片套卡片 + 小字号 + 主操作被隐藏 + 焦点不可见 + 色彩过载"整体偏离 macOS 桌面语言。**P0 3 项、P1 26 项、P2 18 项**，建议分 3 批实施。

---

## P0 — 阻断理解或明显残缺（3 项）

### P0-1 键盘焦点不可见，QToolButton 全族无焦点样式
- **证据**：`selection_surfaces.py:21-31` 主动剥离 `State_HasFocus`；`design_system_v11.py:53-58,84-89` 侧栏/筛选段 `outline:0` 且 focus 底色=hover；`styles.py` 中 QToolButton 全族 0 条 `:focus`；全仓 0 处 `setTabOrder`。
- **违反**：无障碍（焦点必须始终可见，WCAG 2.4.7）、直接操纵。
- **改法**：补 `:focus { border:2px solid #2563EB }`（已有 token `focus_border_width=2`），为 QToolButton/列表项/TextBtn 补焦点环，`setTabOrder(搜索→筛选段→表格→详情)`。
- 工作量 **S/M**。

### P0-2 审查页顶部结构断裂：无标题 + 首个控件紧贴窗口顶边
- **证据**：`review.png` / `narrow-review.png`。`design_v1_review_task_closure.py:102-131` 把导入/扫描/导出按钮 `deleteLater`，`:154-163` 隐藏 `review_header`；`app.py:1787-1789` 上边距 0；`:1808-1810` "无票号疑似重复复核" 裸加进主布局，成为页面第一行且像被裁切。其余 5 个页面都有标题。
- **违反**：清晰性、一致性、桌面平台适配（页首应有页面语境）。
- **改法**：恢复紧凑一行 `PageHeader`（20px 标题 + 12px 副标题）；"无票号疑似重复复核" 移入「更多/批量」；主操作改为常驻但降权的 34px 图标+文字按钮（不要删控件）。
- 工作量 **M**。

### P0-3 概览「当前概况」右侧摘要重影（文字叠字，不可读）
- **证据**：`overview.png` 及放大图 `zoom-overview-activity.png`；"待审核 20 张""可导出 2 组 · 本月 ¥2287.50" 以两种字号/位置相互覆盖。同一 `ActivityTimeline` 独立复现（`zoom-timeline-repro.png`）干净 → 页面级生命周期问题，疑似刷新代际/异步基线重排时旧行未同步移除（`ActivityTimeline.clear()` 用 `deleteLater`）。
- **违反**：清晰性（文字不可读）。
- **改法**：刷新时先 `hide()+setParent(None)` 再重建（或 `setUpdatesEnabled(False)` 批量替换）；修复前先在 `_refresh_overview_page` 打印卡片子树确认重叠来源。
- 工作量 **S**。

---

## P1 — 明显偏离 Apple 标准（26 项）

### A. 布局与信息架构

| ID | 问题 | 证据 | 改法 | 工作量 |
|---|---|---|---|---|
| P1-1 | 审查页工具栏只剩"超长搜索 + 更多"，同步/导入/导出等主操作被藏 | `review.png`（搜索框约 1106×34，右侧仅 95px"更多"）；`app.py:1857-1971`；`design_v1_review_task_closure.py:111-139` | 搜索固定 280-320px；右侧常驻「同步」「导出」2 个 34px 图标+文字动作，其余入 More | M |
| P1-2 | 概览 4 张 KPI 卡全部红/橙数字 + 彩边，颜色不再编码严重度；黄色"20 张待处理"chip 与蓝色主按钮并列 | `overview.png` | 中性计数用 label 色，仅"解析失败/异常"用 danger；chip 改次级文字或删除 | S |
| P1-3 | 卡片套卡片：工具栏/筛选条/表格/预览/详情 5 个 1px 描边 + 10px 圆角面板 | `review.png`；`styles.py:164-168,1946-1951`；`app.py:2287-2311` | 列表/预览/Inspector 改 QSplitter + 1px separator，仅确有层级处保留圆角卡 | M |
| P1-4 | 详情面板固定 352px，1440 宽时"替换原件"被裁切；<1200px 隐藏日期列 | `review.png`（无"替换原件"）vs `review-selected-3.png`（有）；`review_layout.py:20-24,403-404` | 右栏 320-420 弹性；材料行按钮收进"⋯"；<1200px 自动折叠详情（已有 Ctrl+B） | M |
| P1-5 | 设置 4 层导航（外层侧栏 + 常用/高级 + 二级导航 + 账号卡列表），信息页 760px 封顶导致右侧 1/3 空白 | `settings-advanced-*.png`；`app.py:5982-5987,6067-6086`；`settings_baseline.py:29-38` | 扁平为"侧栏 7 分区 + 单面板"，删除"常用/高级"模式层；列表改紧凑表格；面板宽度放开到 900/自适应 | L |
| P1-6 | 常用设置页原生 #F3F3F3 灰画布（画中画）+ 模式栏右侧浮动说明句 + 卡片右侧 60% 空白 | `settings-common.png`；`app.py:6019-6048`；`styles.py:1123-1124`（已有 `SettingsScroll` 未用） | 滚动区改用 `SettingsScroll`；卡片 max-width 720-760 居中；说明句并入页头 | S |
| P1-7 | 导出页层级混乱：5 个 pill 混排数字/文本；"已通过发票 0 张"用红色；信息行加 ✓ 像"已通过"；3 个同级全宽次按钮；中间列空态是空白描边框 | `export.png`；`app.py` 导出页构建段 | 分组 label+值（去 pill 容器）；0 用 secondary 色；空态给图标+说明+主操作；左列动作收进"⋯"或顶部工具栏 | M |
| P1-8 | 空/错/加载态缺失：`LoadingCard` 定义未用；加载失败弹 `QMessageBox.critical`；空态 3 张步骤卡 + 6 个 CTA | `ui_components.py:642`；`app.py:7324,2176-2282`（code-only） | skeleton/spinner；错误改内联 banner + 重试；空态 1 主 + 1 次操作 | M |
| P1-9 | AI 配置三套状态措辞（未启用/已禁用/关闭），且"API Key 已安全保存"由展示层无条件改写（缺失/环境变量也显示已保存） | `settings-advanced-ai.png`；`settings_pages_baseline.py:452-454`；`app.py:4899,4930,4986` | 统一 未启用/已启用/已暂停；Key 行显示真实来源（未配置/环境变量/凭据管理器），缺失时禁止启用；删除展示层改写 | S |
| P1-10 | 数据与备份页 5 个同级按钮，"恢复"与"备份"同权重（恢复会覆盖现有数据） | `settings-advanced-data.png`；`app.py:5667-5691` | 主操作=完整备份；恢复独立+危险色+确认 sheet（先自动备份） | S |

### B. 组件与交互

| ID | 问题 | 证据 | 改法 | 工作量 |
|---|---|---|---|---|
| P1-11 | 列头点击=弹筛选而非排序，无排序指示；每列表头还都挂筛选小图标 | `app.py:2151`；`review_toolbar_filter_fixes.py:309-322`；全仓无 `setSortingEnabled` | 列头点击排序 + ▲▼；筛选改列头右侧独立 16px 漏斗图标 + popover | M |
| P1-12 | 行高 24px、表格 12px、表头 34px、金额左对齐 | `review_workspace_baseline.py:21`；`styles.py:404-412`；`design_tokens.py:86` | 行高 28-32、表格 13px、表头 28-30 半粗、金额右对齐 | M |
| P1-13 | 选中态 #EFF6FF 与白底对比约 1.07:1；hover 与斑马纹同色 | `styles.py:404-423`；`ui/qss.py:332-349` | 选中=accent 填充+白字或 3px accent 左条；hover #EEF2F6；非活动窗口 #E5E5EA | S |
| P1-14 | 状态徽章对比度 2.86-3.95:1（12px 粗体需 4.5:1） | `styles.py:211-239` | 用语义 token 文本色（#B54708/#067647/#B42318）配浅底 | S |
| P1-15 | 对话框默认按钮/破坏性语义错误：证据框 Enter=取消；卖家记忆 Enter 即删且无确认；删除用"是/否" | `evidence_dialog.py:83`；`seller_preferences_dialog.py:39-47`；`app.py:8536,9697,4786` | 保存类默认=保存、Esc=取消；删除记忆红色+确认；删除确认改动词标签且默认取消 | S |
| P1-16 | 标准按钮显示英文（Save/Cancel/Close），中文界面混排；全仓无 QTranslator | `claim_reason_dialog.py:27,54`；`financial_fields_dialog.py:52`；`duplicate_review_dialog.py:50`；`seller_preferences_dialog.py:39` | 安装 Qt zh_CN 翻译，或统一 DialogButtonBox 工厂设置中文文本 + 文案测试 | S |
| P1-17 | 改一个字段也要打开 6 字段模态窗；inspector 内联输入控件已存在却被 hide | `invoice_detail_panel.py:3070-3077,4816-4851,3279-3289` | inspector 行双击/编辑就地切换（32px 高），Enter 保存 Esc 取消；复杂表单仍用弹窗 | M |
| P1-18 | 图标按钮无标签、目标偏小："⋯" 40×42 无 tooltip；"收起详情" 22px；表头筛选热区仅 20px | `invoice_detail_panel.py:2868`；`app.py:2128-2133,2792` | 补 accessibleName+tooltip；目标 ≥28-32px；图标 16-18px | S |
| P1-19 | 预览工具条默认隐藏、hover 才出现且 1.2s 自动消失；用户不知道能缩放/旋转/打印 | `preview_mixin.py:142,184-187,262,281-300,373-382`；`review-selected-3.png` | 预览卡顶部常驻 40px 工具条（标题+操作组，按钮 32×32）；hover overlay 仅全屏；去掉自动隐藏 | M |
| P1-20 | "异常"按钮用危险红，与删除类动作混淆（标记异常是可逆操作） | `invoice_detail_panel.py:2794-2795`；`styles.py:790-794` | 异常改二级按钮 + 警告色文字；红只保留给删除/不可逆 | S |

### C. 设计系统

| ID | 问题 | 证据 | 改法 | 工作量 |
|---|---|---|---|---|
| P1-21 | token 双源且值冲突：`styles.py:81-94` accent `#1599BD`/metric 18/page_margin 16/section_gap 12/sidebar 180 vs `design_tokens.py:31,67,72-79` `#2563EB`/16/24/16/208；QSS 靠 8 条字符串 replace 拼装 | `styles.py:1961-1989`；`app.py:56,802` 旧值先应用 | 删除 `styles.py` 旧 token，全部取 `design_tokens`；QSS 模板化；`APP_STYLESHEET` 改为函数调用时序 | M |
| P1-22 | 间距未落 8pt/4pt 网格：1,471 个数值/22 个离散值，off-8pt 37.9%（557 处）、off-4pt 23.5%；高频 10px(114)/6px(87)/14px(34)/18px(18) | `setContentsMargins` 265 调用、`setSpacing` 255 调用、QSS 176 处 | 加 spacing token {4,8,12,16,24,32}，先替换 app/settings/detail 的 margins+spacing，保留例外清单 | M |
| P1-23 | 类型阶梯 off-ramp：14/16/18/20 共 11 处；700×25、800×3；3 套 sans 字体栈 + 1 个假等宽（`Segoe UI, monospace`） | `styles.py:1932`；`design_baseline_styles.py:38`；`ui/qss.py:16` | 收敛 22/17/15/13/12/11；权重 400/500/600（700 仅标题）；中文族统一"PingFang SC → Microsoft YaHei UI → Segoe UI"；等宽用 Consolas | S/M |
| P1-24 | disabled 态 14 组有效规则中 8 组对比 <3:1（最差 1.48/1.66/1.73） | `styles.py:1368-1372,1418-1422,1441,1480` | 统一 disabled token（填充 #E4E7EC + 文字 #667085 ≈4.5:1），删除重复 variant | S |
| P1-25 | 0 阴影、44% 规则同时 fill+border、圆角 7 个值（4/5/6/8/10/999/9999） | 运行时 QSS 统计；`design_tokens.py:93-95` | 圆角收敛 6/8/10（胶囊统一 999）；卡片 fill+separator；弹层/对话框加 1 档轻阴影 | M |
| P1-26 | 图标三语言混用：自定义 SVG + Qt 标准图标 + 彩色 emoji（🟢⚪🔄📥🗑️📁⚠️） | `app.py:1706,1902-1965,8065-8084,10039`；`buyer_warning_controller.py:62-99` | 统一 16px 单色线性 SVG（SF Symbols 风格），去掉 emoji 与平台图标 | M |

---

## P2 — 打磨与一致性（18 项）

1. **预览内原生深灰框 + 黑色滚动条**：`pdf_preview_controller.py:112-121` 未设 `frameShape(NoFrame)`/QSS；像素取样内框 `#787878`，卡片边框 `#E5E7EB` → 白底 + 8px 细滚动条 + radius 8 内裁（S）。
2. **全站滚动条不统一**：导入页外层、导出列表、预览内嵌均出现原生深色滚动条 → 统一细滚动条 QSS（S）。
3. **模式开关不像分段控件**：`常用设置/高级设置` 选中态是蓝色实心主按钮；已有 `SegmentControl` 未复用（`app.py:5992-6006` → 用统一分段控件 36px、浅蓝选中（S）。
4. **买家警告首屏可能只见 1 行且内滚动 + emoji ⚠️ + 重复 QSS**：`design_tokens.py:98-104`（44-76px）；`review_toolbar_filter_fixes.py:470-481`；`buyer_warning_controller.py:62-99` → 统一 AlertBanner（线性图标+标题+2 行摘要+"查看详情"popover），不设内滚（S）。
5. **缩放提示谎称 Ctrl+±/Ctrl+0，比例固定显示 100%**：`preview_toolbar.py:82,84-88`；`preview_mixin.py:1401-1414` → 注册快捷键 + 动态百分比 + 比例菜单（S）。
6. **对话框外观不统一**：`dialog_form.py:17-56` 仅 2 个对话框使用，其余默认 9px 边距/无标题/无底部留白 → 统一 DialogShell（20/18 边距、15px 半粗标题、按钮右对齐）（S）。
7. **inspector Tab 与分区同名"基本信息"，352-400px 面板塞 11 个按钮**：`invoice_detail_panel.py:2068,3040` → 删重复分区标题；材料行按钮收进"⋯"（M）。
8. **预览空态/不支持/失败无恢复动作**：`preview_mixin.py:498-517` → 空态=图标+标题+一句说明+主按钮（补充原件/外部打开/定位）（S）。
9. ~~`mobile_upload_dialog.py` 204 行死代码~~ **已删除（技术债 Wave 0，PR #202）**：`app.py` 仅 import 不实例化，已移除。
10. **记录头信息过载**（6 个元素全 11px，含永久教学文案"点击列标题可筛选"）：`styles.py:392-403`；`review_toolbar_filter_fixes.py:303-306` → "发票记录 · 26 张"+右侧 2 个 ≥28px 操作，提示移入 tooltip/空态（S）。
11. **状态栏信息重复且居中，左侧计数被隐藏**：`app.py:2399-2459`；`review_paging.py:87-90` → 左总数/筛选，右选中合计；版本号 11px（S）。
12. **多选批量条撑高列表导致布局跳动**：`ui/components/batch_review_bar.py:16-50` → 选中时替换筛选条或浮动底条，不改变列表高度（M）。
13. **筛选条像统计卡而非分段控件**：`design_system_v11.py:284-321`；`stat_card.py:36-57` → 灰轨道+清晰选中 pill，label 居中、计数次级小字（S/M）。
14. **术语不统一**："状态/资料"；"通过所选…" vs "通过所选 (n)"；"加入报销组" vs "关联到当前报销组" → 建术语表（S）。
15. **导入页邮箱卡横向滚动条裁切账号行**：`imports.png` → 卡片内禁止横向滚动/换行（S）。
16. **导入页来源三卡像输入框**（选中有蓝边，无勾选/单选标记）：`app.py:5250-5260` → 改分段控件或卡片+勾选标记（S）。
17. **无深色模式**：0 处 QPalette/colorScheme，仅一套浅色 QSS；需先完成 P1-21/22/23 再引入 DARK 色板与 QSS 工厂，约 3-5 人日（L）。
18. **动效与高 DPI**：唯一动画 190ms OutCubic 合规，但无 reduced-motion 适配、无状态过渡；131 条 1px 边框 + 8 条 1px 分隔线在 125%/150% 下发虚 → 读取系统动画偏好置 0；细线用 devicePixelRatio 感知绘制（S/M）。

---

## 已符合 HIG，建议保持

- 设计 token 层存在（`design_tokens.py`：颜色/字号/圆角/控件高/焦点宽），canonical QSS 单一蓝 accent `#2563EB`/`#1D4ED8`。
- 对比度：主文本 16.03、次级 7.23、强调 4.86、状态色 5.02-5.95 均通过；placeholder/边界偏淡属 P2。
- 唯一动画 190ms OutCubic 落在 Apple 150-250ms 区间；19 个 SVG 图标 currentColor（DPI/暗色友好）。
- 设置高级页 master-detail 结构清晰、分区标题+分隔线可读（`settings-advanced-mailbox.png` 是全场最接近 macOS 系统设置的页面）。
- 响应式：窄窗侧栏折叠为图标轨、表格隐藏次要列（`narrow-review.png`）。
- 删除确认默认"否"；日期范围/API Key 有行内校验；预览有 Ctrl+滚轮缩放/双击全屏/Esc；预览工具条按钮已有 accessibleName。
- 输入框内 Enter/Del/Ctrl+E 不触发全局动作（`app.py:2930-2936,3031-3039`）。

---

## 建议实施批次

| 批次 | 内容 | 预计 |
|---|---|---|
| 第 1 批（S） | P0-1/2/3；P1-9/11/12/13/14/15/16/20/24 | 1-2 天 |
| 第 2 批（M） | P1-1/4/7/8/17/18/19/21/22/23/25；P2-1/2/3/4/5/10/11 | 2-3 天 |
| 第 3 批（L） | P1-5/6/10/26；P2-17/18（设置 IA 扁平化、图标语言统一、暗色模式/高 DPI） | 3-5 天 |

**验收标准**（每批）：
1. 用 `capture_v2.py` 重跑生成同机位截图，逐项前后对比；
2. 纯键盘走查一遍主流程（Tab 焦点始终可见、Enter/Esc 语义正确）；
3. 对比度用 WCAG 公式复核（正文 ≥4.5:1、大字号/UI ≥3:1）；
4. 125%/150% DPI 各截一张主界面；
5. `python -m unittest tests.test_hci_v1 tests.test_settings_center ...` 等壳 UI 基线测试不回归。
