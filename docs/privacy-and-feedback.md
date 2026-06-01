# 隐私与反馈说明

Invoice Hub 按本地优先方式设计。默认流程不上传发票原件、邮件正文、PDF 文本、SQLite 数据库或 Excel 导出包。

## 默认本地处理

默认在本机处理：

- 邮箱扫描结果
- 下载或导入的发票原件
- 解析出的发票字段
- 本地 SQLite 数据库
- Excel 台账和报销组附件包

邮箱授权码或应用密码应存入操作系统凭据管理器，不应写入 `config.json`、日志、Issue 或截图。

## AI 分类

AI 分类默认关闭。显式启用 AI 时，只发送脱敏后的邮件主题和发件人，用于判断邮件是否可能是发票或 receipt。

不会发送：

- 邮件正文
- PDF/OFD 文本
- 附件文件
- 发票图片
- SQLite 数据库
- Excel 导出包

## 脱敏诊断包

诊断包只允许包含：

- `app_info.json`
- `latest.log.redacted`
- `config.redacted.json`
- `environment.txt`
- `privacy_scan_result.txt`

诊断包不会打包：

- `invoices.db`
- `attachments/`
- `exports/`
- PDF/OFD/图片原件
- Excel/ZIP 原件
- 邮箱授权码
- API Key
- 完整 tokenized URL

脱敏规则会处理邮箱地址、手机号、10 位以上数字串、URL query，以及 `api_key`、`token`、`password`、`auth_code`、`authorization`、`secret`、`credential` 等字段。

## 提交反馈

提交 GitHub Issue 前请检查：

- 不上传真实发票、receipt、行程单、水单、支付截图。
- 不上传 Excel 报销包或 SQLite 数据库。
- 不上传邮箱授权码、API Key、Cookie 或完整下载链接。
- 优先上传应用生成的 `InvoiceHub-diagnostics-YYYYMMDD-HHMMSS.zip`。
