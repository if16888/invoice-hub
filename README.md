# Invoice Hub

Invoice Hub 是一个本地优先的报销资料整理助手。它面向个人员工在提交报销前的整理环节：从邮箱、本地目录和手机扫码上传通道收集发票、receipt 与证明材料，辅助解析、去重、分类、人工确认，并导出 Excel 台账和报销组附件包。

它不是企业费控系统，也不替代 Concur、飞书、钉钉、合思等企业报销平台。它只负责把提交前散落的材料整理清楚。

## 核心能力

- 桌面审核工作台：发票列表、搜索筛选、原件预览、字段编辑、审核状态和报销组导出。
- 标准 IMAP 邮箱扫描：支持 QQ、163/126 和自定义 IMAP 配置。
- 本地导入与扫码上传：用于收集本地 PDF/OFD/图片和手机端材料。
- 报销组导出：生成 Excel 台账、manifest 和附件包，保留用户确认后的分类与备注。
- 脱敏诊断反馈：可导出只含日志摘要、环境信息和脱敏配置的诊断包。

## 隐私设计

- 默认不上传发票原件、邮件正文、PDF 文本、SQLite 数据库或 Excel 导出包。
- 邮箱授权码/应用密码应托管在操作系统凭据管理器中，不写入 `config.json`。
- AI 分类默认关闭。显式启用 AI 时，仅发送脱敏后的邮件主题和发件人，不发送附件、PDF 文本、图片、数据库或 Excel。
- 诊断包采用 allowlist，只包含脱敏日志、脱敏配置、环境摘要和隐私扫描结果。

## 快速开始

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

## 项目文档

- [用户快速开始](docs/user-quickstart.md)
- [开发架构设计](docs/architecture.md)
- [项目开发路线](docs/roadmap.md)
- [隐私与反馈说明](docs/privacy-and-feedback.md)
- [标准 IMAP 邮箱配置](docs/generic-imap-mailboxes.md)
- [发布检查清单](docs/release-checklist.md)
- [已知问题](docs/known-issues.md)

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

## 许可证

Invoice Hub 采用 Apache License 2.0。第三方依赖和打包组件的许可说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
