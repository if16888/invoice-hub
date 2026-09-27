# Invoice Hub — Design System & UX Standards (DESIGN.md)

> **Version**: 1.0.0 (Enterprise Business Edition)  
> **Source of Truth**: Open Design / Antigravity Agent Workspace  
> **Target Audience**: Financial Controllers, Reviewers, Enterprise Employees, Automation Agents  

---

## 1. 核心设计原则 (Core Principles)

1. **商务稳健 (Enterprise & Trustworthy)**
   - 界面采用中性蓝灰色系与清晰的视觉层级，摒弃浮夸的动画与虚化拟物。
   - 所有数值必须精准、严肃、无歧义，符合企业财务软件的严谨质感。

2. **高信噪比与高效易用 (High Signal-to-Noise & Frictionless)**
   - 优先展示高频核心操作：批量审核、快速搜索过滤、一键核验。
   - 减少页面跳转，核心审核任务采用“列表 + 右侧票据详情/原件对照”的分屏联动架构。

3. **零低级错误与财务防错守则 (Zero Low-Level Mistakes & Safe Guards)**
   - **价税平衡恒等式**：`价税合计 = 不含税金额 + 税额`，原型中展示的所有金额必须在数学上完全平齐，保留 2 位小数并使用千分位。
   - **大写金额一致性**：中文大写金额（如 `壹佰贰拾元整`）必须与阿拉伯数字精确对应，不得出现错别字或倒挂。
   - **发票身份唯一性**：全国统一发票代码（10/12位）及发票号码（8/20位），无号码凭证依靠物理哈希与开票日期联合防重。
   - **抬头税号合规性**：对购买方统一社会信用代码（18位）实施校验，若非企业自身抬头或税号不符，必须给出醒目的黄色/红色预警，禁止静默通过。
   - **破坏性操作二次防线**：批量驳回、标记作废或永久删除必须有二次确认提示，重要变更记录审计流水。

---

## 2. 视觉规范契约 (Design Tokens)

### 2.1 调色板 (Color Palette)

```css
:root {
  /* Brand / Primary Accent (Enterprise Navy Blue) */
  --primary-50:  #EFF6FF;
  --primary-100: #DBEAFE;
  --primary-500: #2563EB;
  --primary-600: #1D4ED8;
  --primary-700: #1E40AF;

  /* Neutrals & Surfaces */
  --bg-page:     #F8FAFC;  /* Slate 50 */
  --bg-surface:  #FFFFFF;
  --bg-subtle:   #F1F5F9;  /* Slate 100 */
  --border-light:#E2E8F0;  /* Slate 200 */
  --border-dark: #CBD5E1;  /* Slate 300 */

  /* Typography Colors */
  --text-main:   #0F172A;  /* Slate 900 (High contrast) */
  --text-sub:    #475569;  /* Slate 600 */
  --text-muted:  #94A3B8;  /* Slate 400 */

  /* Semantic Status Colors (Financial Grade) */
  --success:     #059669;  /* Emerald 600 (已核验 / 已归档) */
  --success-bg:  #ECFDF5;
  --success-border: #A7F3D0;

  --warning:     #D97706;  /* Amber 600 (待人工复核 / 抬头不符) */
  --warning-bg:  #FFFBEB;
  --warning-border: #FDE68A;

  --danger:      #DC2626;  /* Red 600 (金额异常 / 重复作废) */
  --danger-bg:   #FEF2F2;
  --danger-border: #FECACA;

  --info:        #0284C7;  /* Sky 600 (解析中 / 同步中) */
  --info-bg:     #F0F9FF;
  --info-border: #BAE6FD;
}
```

### 2.2 排版与财务字体 (Typography & Financial Numerics)

- **主字体栈**：`Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif`
- **等宽财务数字**：表格、金额、发票号、税号统一启用 `font-variant-numeric: tabular-nums`，确保小数点与千分位对齐。
- **字阶规范**：
  - 页面大标题：`20px / 600`
  - 模块标题 / 卡片标题：`15px / 600`
  - 正文字体：`13px / 400`
  - 表格内容：`12.5px / 400`
  - 标签与微提示：`11px / 500`

### 2.3 间距与圆角 (Spacing & Geometry)

- **导航栏宽度**：`220px`（深色商务灰底，高辨识度图标与徽章）
- **圆角规范**：
  - 小型控件 / 按钮 / 输入框：`6px`
  - 数据卡片 / 模态弹窗：`8px`
- **阴影规范**：
  - 卡片轻微阴影：`0 1px 3px 0 rgb(0 0 0 / 0.05), 0 1px 2px -1px rgb(0 0 0 / 0.05)`
  - 浮动动作条：`0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)`

---

## 3. 四大核心分页面架构 (Sub-page Specifications)

### 3.1 页面 1：数据概览与统计分析 (Overview & Analytics)
- **目标**：为财务及审核人员提供全貌洞察与行动待办入口。
- **关键模块**：
  - **4项核心指标卡**：本期待审核张数、待报销总额（含环比）、合规通过率、异常风险件数；
  - **快捷行动面板**：一键同步指定邮箱、拖拽快速导入、开启手机上传、导出上月归档；
  - **异常风险发票速查**：展示税号不符、金额超标、疑似重复的急件，支持一键定位审核；
  - **支出结构分布**：按差旅、办公、招待、研发费用类别展示占比与预算水位。

### 3.2 页面 2：发票智能审核工作台 (Review Workbench)
- **目标**：高频、沉浸式、不出错的票据审查与结构化校验。
- **关键模块**：
  - **全功能筛选条**：状态筛选（全部 / 待审 / 合规 / 异常）、开票月份筛选、费用类别、买方抬头；
  - **批量动作浮条**：多选发票后底部弹出沉浸式工具栏（批量通过、批量变更分类、标记异常、一键导出）；
  - **左侧数据表格**：密实排布但字距舒适，状态 Badge、发票号码、开票日期、销售方、价税合计、附件类型标识；
  - **右侧双重视图**：
    - **票据电子凭证视图**：真实的全国统一发票版式模拟，清晰呈现发票代码、号码、开票日期、购买方与销售方全称、统一信用代码、明细项、税率、价税合计等；
    - **合规核验与纠错面板**：自动提示“购买方税号与公司档案一致”、“价税平衡验证通过”，支持一键“审核通过 (Ctrl+Enter)”与“退回驳回 (Esc)”。

### 3.3 页面 3：发票归集与同步中心 (Import & Sync Hub)
- **目标**：管理多渠道发票汇聚任务，掌握解析进度与去重细节。
- **关键模块**：
  - **多邮箱自动抓取**：展示企业邮箱、QQ、网易等同步状态、最近拉取时间、成功/重复张数；
  - **本地批量导入**：支持批量拖入文件夹、PDF/OFD/XML/数电发票，实时进度条；
  - **移动端局域网传输**：显示手机端扫码直传二维码、动态配对码及当前连接设备数；
  - **导入去重审计流**：列出最新批次的处理结果（如“某发票已跳过：物理文件哈希相同”或“已更新元数据”），有据可循。

### 3.4 页面 4：报销归档与导出构建器 (Export & Reimbursement Builder)
- **目标**：生成符合财务审计要求的报销凭证包与 Excel 汇总台账。
- **关键模块**：
  - **批次信息配置**：报销单标题、归属项目/部门、报销人、费用月份；
  - **待报销发票清单挑选**：勾选计入报销单的发票，右上角实时动态累计张数与价税合计；
  - **附件智能重命名配置**：内置规范模板，如 `[{序号}]_{报销人}_{开票日期}_{类别}_{金额}元_{销售方}.pdf`；
  - **导出预览与打包**：一键生成标准报销清单（含封面明细汇总）并下载归档 ZIP。
