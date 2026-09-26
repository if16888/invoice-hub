# 已知问题与当前限制

本文件只记录**用户需要知道**的限制，不作为内部开发 TODO 列表。开发任务请使用 GitHub Issues。

## 解析与下载

- **OFD、图片和扫描件**：字段解析能力仍弱于结构化 PDF；无法可靠识别时会保留为待补全记录，需要人工确认。
- **网页发票下载**：登录、验证码、一次性链接过期、供应商页面改版都可能使自动下载失败。此时可手工下载后使用本地导入。
- **浏览器自动化**：Windows 包携带 Playwright driver/runtime integration，但不打包完整 Chromium。自动网页下载依赖本机可用浏览器或现有 fallback。

## 手机上传

- 手机与电脑必须处于可互通的局域网。
- 企业 Wi-Fi、访客网络、AP isolation、VPN 或 Windows 防火墙策略都可能阻止手机访问桌面会话。
- 浏览器/WeChat 行为与桌面端自动化测试不是同一类证据；正式支持声明应以真实设备验收为准。

## Windows 安装

- 没有可信 Authenticode 签名或足够下载信誉时，Windows 可能显示 SmartScreen / Unknown Publisher。
- 卸载默认不删除用户 AppData、Documents 导出目录或 Windows Credential Manager 中的凭据，避免误删个人数据。
- 因此“卸载后重装”不等于“全新 Windows 用户首次安装”。

## 产品边界

- 解析结果需要人工复核，不应直接视为财务事实。
- 证明材料按发票或报销组关联，不是企业级档案管理系统。
- 不提供企业审批、预算控制、云同步、多人协作、自动付款或直接提交第三方费控系统。

## 发布验证

发布前以 [release-checklist.md](release-checklist.md) 和 [REAL_WORKFLOW_ACCEPTANCE.md](REAL_WORKFLOW_ACCEPTANCE.md) 为准。

自动化测试、hosted CI、synthetic screenshot matrix 和 physical-Windows acceptance 是不同证据层级；不得用其中一个替代另一个。
