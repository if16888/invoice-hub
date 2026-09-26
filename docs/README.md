# Invoice Hub 文档导航

本目录按“用户使用 / 隐私安全 / 发布验证 / 开发设计 / 历史记录”分层。新文档优先放到对应主题目录或本页索引，避免 README 再次膨胀成所有内容的集合。

## 用户使用

- [用户快速开始](user-quickstart.md) — 安装后从配置、导入、审核到导出的最短路径。
- [Windows 下载与安装安全说明](windows-install.md) — Release Assets、SHA256、SmartScreen / Unknown Publisher。
- [标准 IMAP 邮箱配置](generic-imap-mailboxes.md) — 邮箱授权码、应用专用密码和常见 provider。
- [已知问题](known-issues.md) — 当前限制、影响与规避方式。

## 隐私与安全

- [隐私与反馈说明](privacy-and-feedback.md) — 哪些内容可以/不可以上传到公开 Issue。
- [隐私数据流](privacy-data-flow.md) — 邮箱、附件、SQLite、AI、诊断包的数据边界。
- [安全策略](../SECURITY.md) — 漏洞报告与安全响应入口。
- [PySide6 / Qt 许可合规](pyside6-license-compliance.md) — Qt 相关许可与随包文本。

## 发布与验收

- [发布检查清单](release-checklist.md) — 发布前源码、隐私、Windows 包和仓库设置检查。
- [真实工作流验收](REAL_WORKFLOW_ACCEPTANCE.md) — clean install、升级、持久化、DPI 与真实使用闭环。
- [手工 RC 验收](manual-rc-acceptance-checklist.md) — 使用脱敏/可丢弃数据验证导入、审核、材料、导出。
- [CI 验证说明](ci-validation.md) — local-first、PR exact tree 与 master attestation 的职责边界。
- [v0.1.8 release notes](release-notes/v0.1.8.md) — 当前源码 release line 的变化与最终发布合同。

## 架构与开发

- [架构说明](architecture.md) — 模块、SQLite、本地文件、GUI、导出与诊断边界。
- [项目路线](roadmap.md) — 产品阶段与后续范围。
- [Design Baseline v1](DESIGN_BASELINE_V1.md) — 当前桌面端视觉和交互基线。
- [UI 稳定性 review](UI_STABILIZATION_REVIEW.md) — 自动化、截图和人工视觉验收边界。

## 图片资产

- [图片资产规则](images/README.md)
- [产品工作流概览](images/invoice-hub-overview-v2.svg)
- [发票审核工作台示意](images/desktop-review.svg)
- [手机上传示意](images/mobile-upload.svg)
- [报销导出示意](images/claim-export.svg)

所有公开图片必须使用**合成或完全脱敏**内容。真实票据、邮箱、税号、金额、数据库、授权码、API Key、本机私有路径和完整 tokenized URL 不得进入仓库图片。

## 文档维护规则

1. README 只保留产品定位、快速开始、核心能力和文档入口。
2. 会随时间变化的“是否已经正式发布”状态只以 GitHub Releases 为权威，不写死在静态文档。
3. 发布验收文档必须明确区分 source test、CI、packaged Windows、physical Windows 和 real-device evidence。
4. 历史设计记录不得继续作为当前 release gate 的权威来源。
5. 新增截图前先使用合成数据跑截图工具，再人工检查隐私。
