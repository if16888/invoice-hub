# ⚖️ PySide6 开源许可合规与工程规范 (PySide6 License Compliance Engineering Note)

> [!NOTE]
> **免责声明**：本文件为 Invoice Hub 项目内部工程指导说明与最佳实践，非正式法律意见。如涉及商业分发或特定司法管辖区的知识产权合规，请咨询法律顾问或合规专家。

本指南确立了在开发 Invoice Hub 桌面图形界面 (GUI) 时，使用 PySide6 (Qt) 库的开源合规底线要求、工程限制与未来的发布审查标准。

---

## 1. 开源许可与工程边界

Invoice Hub 桌面端 UI-001 阶段使用 **PySide6** 库构建。PySide6 (Qt for Python) 支持 LGPL-3.0、GPLv3 以及商业许可等多种双重许可路径。在当前的 UI-001 开发阶段，本项目采用符合 LGPL-3.0 规范的动态链接兼容开发路径，以保障未来开源转型的平滑度与安全性，并最大化避免商业分发中的潜在许可纠纷。开发过程中必须严格遵守以下工程规范：

### 🛠️ 1.1 已审查 Qt 模块范围 (Reviewed GUI Scope)
当前 GUI 桌面端允许使用以下已审查 Qt / PySide6 模块：
1. **`PySide6.QtCore`** — 提供事件循环、基础 IO、核心数据类型和信号槽机制。
2. **`PySide6.QtGui`** — 提供窗口系统集成、基本绘图、字体、颜色、图标及桌面服务 (`QDesktopServices`)。
3. **`PySide6.QtWidgets`** — 提供预制的扁平化桌面交互控件与布局管理器。
4. **`PySide6.QtPdf`** — 用于本地 PDF 原件预览，不上传 PDF 内容，不修改 Qt/PySide 源码。
5. **`PySide6.QtPdfWidgets`** — 用于 `QPdfView` 桌面预览控件。
6. **`PySide6.QtNetwork`** — 用于局域网扫码上传时枚举本机网络地址。

> [!IMPORTANT]
> **工程禁令**：
> 1. **严禁引入任何新的 Qt / PySide6 其他模块**（例如 Web 内核、图表、定位、蓝牙、多媒体或网络认证模块），除非经过明确的许可与打包合规评审。
> 2. **基础社区版界面代码 (Community UI) 必须仅依赖公开的核心接口**，不得导入或引用任何 Pro/private/template-pack 模块或代码，保持开源核心边界清晰。

---

## 2. 详细合规与审查矩阵 (License Review Matrix)

| 模块/技术项 | 合规状态 | 规范与防范要求 |
| :--- | :---: | :--- |
| **PySide6.QtCore** | ✅ **Allowed** | 基础组件，允许使用。 |
| **PySide6.QtGui** | ✅ **Allowed** | 基础组件，允许使用。 |
| **PySide6.QtWidgets**| ✅ **Allowed** | 基础组件，允许使用。 |
| **PySide6.QtPdf** | ✅ **Allowed / Reviewed** | 当前仅用于本地 PDF 预览；不作为 Web 渲染或远程内容执行引擎。 |
| **PySide6.QtPdfWidgets** | ✅ **Allowed / Reviewed** | 当前仅用于 `QPdfView` 桌面控件；随 PySide6 动态库分发。 |
| **PySide6.QtNetwork** | ✅ **Allowed / Reviewed** | 当前仅用于局域网地址枚举；不得扩展为默认联网传输或远程遥测。 |
| **PySide6 (其他附加模块)** | ⚠️ **Requires Review** | 如 `QtWebEngine`, `QtCharts`, `QtDataVisualization`, `QtLocation`, `QtNetworkAuth`, `QtBluetooth`, `QtMultimedia` 等。这些模块有些可能存在更复杂的商业附加约束或 GPL 级级联影响，必须进行显式审查。 |
| **PyQt (PyQt6 / PyQt5)** | ❌ **Forbidden** | PyQt 系列主要采用 **GPLv3** 协议（或需购买其专属商业授权），其开源路径具备强烈的传染性。如果混入，会产生与本项目闭源 Pro 模块/模板包在商业分发时的开源合规冲突（除非单独进行额外的商业授权购买和专门合规评估）。**在获得单独的商业/许可合规评审通过前，严禁导入或混用 PyQt**。 |
| **静态链接 (Static Linking)**| ❌ **Forbidden** | 静态链接 Qt/PySide 会导致用户无法动态替换 Qt 运行时动态链接库，直接违反 LGPL 协议的动态链接替换要求。**必须使用动态包装链接**。 |
| **修改 Qt/PySide 源码** | ❌ **Forbidden** | 严禁对 Qt 或 PySide6 的库本身源码进行任何就地修改。如有需要，应当在应用层以继承、包装的形式处理。 |
| **应用商店打包发布** | ⚠️ **Requires Review** | 针对 Windows Store 或 Mac App Store 等存在 DRM 硬件限制的渠道打包，由于可能阻碍用户行使 LGPL 替换库的权利，上线前必须做合规隔离评估。 |

---

## 3. 未来正式发布与构建合规流程

在进行官方正式打包构建（包括 Pro 版商业分发或公开社区版发布）之前，发布管线中必须自动包含以下审计要素：

1. **依赖许可清单 (Dependency License Inventory)**：
   自动检测打包出的二进制依赖树，输出完整的第三方库许可备案。
2. **免责与第三方声明 (`THIRD_PARTY_NOTICES.md`)**：
   在分发包根目录和关于对话框中，清晰声明该软件使用了 Qt 和 PySide6 库，它们受 LGPL-3.0 许可协议保护，并附带动态链接说明。
3. **许可证书文件拷贝**：
   官方构建的分发压缩包/安装器中必须内置拷贝存放：
   - `licenses/LGPL-3.0.txt`
   - `licenses/GPL-3.0.txt` (如有需要)
4. **源码引用声明 (Source-Location Note)**：
   在文档和关于界面中提供 Qt/PySide 官方源码的下载获取链接（如 `https://www.qt.io/download` ），履行 LGPL 的源码告知义务。
5. **关于对话框归属 (About Dialog Attribution)**：
   UI 中如果包含“关于 (About)”对话框，必须清晰标注 Qt 徽标和许可说明，说明用户可通过动态链接库进行自由替换。

## 4. 当前发布前状态

- 根目录必须包含 `LICENSE` 和 `THIRD_PARTY_NOTICES.md`。
- portable zip 与 Inno Setup 安装包必须包含 `LICENSE` 和 `THIRD_PARTY_NOTICES.md`。
- 发布包不得包含 `runtime/`、`config.json`、`invoices.db`、真实票据样本或 Playwright Chromium 浏览器二进制。
- 当前 PySide6 使用范围必须与本文件“已审查 Qt 模块范围”保持一致；新增模块前必须更新本文件和对应测试。
