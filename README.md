# Invoice Hub

**本地优先的发票审核与报销整理工具。**

| 当前公开下载版本 | 当前开发版本 | 状态 | 推荐 |
| --- | --- | --- |
| [Invoice Hub v0.1.2](https://github.com/if16888/invoice-hub/releases/tag/v0.1.2) | Invoice Hub v0.1.3-rc1 | early preview / 早期可试用 | 先用少量脱敏样本试跑 |

Invoice Hub 是一个本地优先的报销资料整理助手，用来在提交报销前，把散落在邮箱、本地文件夹和手机里的发票、收据、截图、证明材料整理成可审核、可归组、可导出的资料包。

它不是企业费控系统，也不替代 Concur、飞书、钉钉、合思等企业报销平台；它专注于“提交之前”的个人整理环节。

![Invoice Hub overview](docs/images/invoice-hub-overview.png)

> 预览图使用合成/脱敏示例数据，不包含真实发票、邮箱、税号、金额、数据库、授权码或 API Key。

## 立即试用

### 普通用户优先

请在 [GitHub Releases](https://github.com/if16888/invoice-hub/releases/latest) 下载最新版本。当前公开下载版本请以 Releases 页面为准。

- [Latest Release](https://github.com/if16888/invoice-hub/releases/latest)
- `InvoiceHub-Setup-*.exe`：Windows 安装包。
- `InvoiceHub-windows-x64-*.zip`：免安装 portable 包。
- `checksums.txt`：发布资产 SHA256 校验值。

安装或解压后启动 `Invoice Hub`。建议先用少量脱敏样本试跑；确认流程符合预期后，再在本机导入自己的报销材料，并避免把运行数据上传到公开 Issue。

### 开发者本地启动

```powershell
pip install -r requirements.txt
pip install -r requirements-desktop.txt
python -m scripts.invoice_fetch desktop
```

命令行入口：

```powershell
python -m scripts.invoice_fetch --help
python -m scripts.invoice_fetch --import-dir .\your_invoices_path
```

邮箱凭据建议存入 Windows Credential Manager：

```powershell
cmdkey /generic:invoice_mail_auth_code /user:your_email@example.com /pass:<IMAP授权码或应用专用密码>
```

## 解决什么问题

很多报销失败不是因为系统复杂，而是提交前资料没有整理好：

- 发票散落在邮箱、本地目录、手机相册和聊天记录里。
- 同一张发票可能重复下载、重复上传或文件名混乱。
- 发票字段解析不完整，需要人工补金额、日期、销售方、分类和备注。
- 需要把一批已确认的材料归到同一个报销组，再导出给企业报销系统或财务同事。
- 反馈问题时不希望把真实发票、数据库或邮箱授权码发到 GitHub Issue。

Invoice Hub 试图把这些提交前的整理动作放在本机完成。

## 工作流

**收集 -> 去重 -> 审核 -> 归组 -> 导出**

1. 收集：从 IMAP 邮箱、本地目录、手机扫码上传入口收集候选发票和证明材料。
2. 去重：根据文件哈希、发票号/金额/销售方等信息和已有记录减少重复材料。
3. 审核：在桌面工作台中查看原件、补全字段、调整分类、确认状态和备注。
4. 归组：把已确认的记录加入一个报销组，保留人工确认后的分类和说明。
5. 导出：生成 Excel 台账、manifest 和附件包，供后续提交或留档。

## 核心功能

- 桌面审核工作台：发票列表、搜索筛选、原件预览、字段编辑、审核状态和报销组操作。
- 邮箱扫描：支持 QQ、163/126 和自定义 IMAP 配置。
- 本地导入：导入 PDF、OFD、图片和 ZIP，复制到本机运行目录后进入同一处理流程。
- 手机扫码上传：在局域网中从手机上传发票或证明材料。
- 报销组导出：生成 Excel 台账、manifest 和附件包。
- 隐私保护诊断：导出脱敏诊断包，便于反馈问题时避免泄露真实票据和密钥。

## 当前状态

Invoice Hub 处于早期可试用阶段，重点是个人本地整理和提交前审核。

已覆盖的方向：

- 本地优先的数据存储和导出。
- 邮箱、本地目录、手机上传三类资料入口。
- 发票/收据证据的解析、分类、去重、人工审核和报销组导出。
- 发布前的隐私检查和打包检查。

仍需谨慎对待：

- 解析结果需要人工复核，不应直接视为财务事实。
- 不提供企业审批流、自动报销、云同步或第三方报销平台自动提交。
- 真实票据、数据库和导出包不应提交到公开仓库或 GitHub Issue。

## 隐私优先提示

- 默认不上传发票原件、邮件正文、PDF 文本、图片、SQLite 数据库或 Excel 导出包。
- 邮箱授权码或应用专用密码建议存入操作系统凭据管理器，不写入 `config.json`。
- AI 分类默认关闭。显式启用 AI 时，仅发送脱敏后的邮件主题和发件人，不发送附件、PDF 文本、图片、数据库或 Excel。
- 运行数据默认保存在本机 `runtime/`，该目录不应提交到 Git。

## 隐私与安全

- `runtime/`、`exports/`、真实发票、邮箱导出、Excel 报销包、数据库和密钥文件都应保持在本地。
- `config.example.json` 只作为示例配置；真实账号、授权码和 API Key 不应提交。
- 诊断包采用 allowlist，仅包含脱敏日志、脱敏配置、环境摘要和隐私扫描结果。
- 公开仓库提供 `scripts/check_repo_privacy.py` 和 `scripts/check_public_export.py` 用于提交前检查。

更多说明见：

- [隐私与反馈说明](docs/privacy-and-feedback.md)
- [隐私数据流](docs/privacy-data-flow.md)
- [安全策略](SECURITY.md)

## 适合谁 / 不适合谁

适合：

- 经常需要整理个人报销材料的员工。
- 希望先在本机审核、补全、去重，再提交企业报销系统的用户。
- 需要同时处理邮箱发票、本地 PDF/OFD/图片和手机端材料的人。
- 关注隐私，希望默认不把原始票据和数据库上传到云端的用户。

不适合：

- 需要企业级审批流、预算控制、组织架构、自动付款或财务系统集成的团队。
- 需要自动提交到 Concur、飞书、钉钉、合思等平台的场景。
- 期望云同步、多端协作或自动审批的用户。
- 期望完全免人工审核的报销流程。

## 反馈问题

普通问题、体验反馈和功能建议请使用 [GitHub Issues](https://github.com/if16888/invoice-hub/issues/new/choose)。

安全或隐私漏洞不要提交公开 Issue，请按 [SECURITY.md](SECURITY.md) 中的安全反馈方式处理。

反馈 Bug 时，请优先上传应用生成的脱敏诊断包，或只提供脱敏后的操作步骤和错误信息。

请不要在 GitHub Issue、截图或附件中上传：

- 真实发票、收据、图片或 PDF/OFD 原件
- `runtime/invoices.db`、Excel 报销包或导出附件包
- 邮箱授权码、API Key、访问令牌或完整下载链接
- 真实邮箱、税号、金额、发票号码、公司内部路径或其他敏感财务信息

## 项目文档

- [用户快速开始](docs/user-quickstart.md)
- [开发架构设计](docs/architecture.md)
- [项目开发路线](docs/roadmap.md)
- [标准 IMAP 邮箱配置](docs/generic-imap-mailboxes.md)
- [发布检查清单](docs/release-checklist.md)
- [已知问题](docs/known-issues.md)
- [PySide6/Qt 许可合规说明](docs/pyside6-license-compliance.md)

## 开发验证

发布或提交前运行：

```powershell
python -m unittest discover -v -s tests -p "test_*.py"
python -m scripts.invoice_fetch --help
python scripts/check_repo_privacy.py
python scripts/check_public_export.py .
python -m compileall -q scripts/invoice_fetch
git diff --check
```

不要提交 `runtime/`、`config.json`、真实发票、邮箱导出、Excel 报销包、数据库或任何密钥。

## License

Invoice Hub 采用 Apache License 2.0。第三方依赖和打包组件的许可说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
