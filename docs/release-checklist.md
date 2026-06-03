# 发布检查清单

本清单用于 Invoice Hub MVP 发布前收口。发布目标是本地优先的个人报销资料整理器，不引入云同步、企业费控、自动审批、复杂 RPA 或完整国际化。

## 代码验证

从仓库根目录运行：

```powershell
python -m unittest discover -v -s tests -p "test_*.py"
python -m scripts.invoice_fetch --help
python scripts/check_repo_privacy.py
python scripts/check_public_export.py .
python -m compileall -q scripts/invoice_fetch
git diff --check
```

如需验证单独生成的公开仓库导出目录，先生成干净 public export，再运行：

```powershell
python scripts/check_public_export.py <public-export-dir>
```

## 隐私检查

- `runtime/` 不得提交。
- `config.json` 不得提交。
- `private/`、`private-data/`、`real-samples/` 不得提交。
- 不得包含真实发票、receipt、OFD、PDF、图片、Excel、ZIP、邮箱导出或数据库。
- 不得包含 `.env`、邮箱授权码、API Key、token、cookie、私钥、证书或完整 tokenized URL。
- 日志、诊断包、README、文档和 Issue 模板不得包含真实个人信息或公司消费信息。
- 脱敏诊断包只允许包含：`app_info.json`、`latest.log.redacted`、`config.redacted.json`、`environment.txt`、`privacy_scan_result.txt`。

## 公开仓库导出

公开仓库应从私有开发仓库导出干净工作树，不直接公开当前私有仓库历史。

发布前版本文案检查：

- 检查 README、Issue templates、user quickstart 中的当前版本号是否已更新。
- 历史 release notes 不回改。
- 安装包示例优先使用 wildcard，例如 `InvoiceHub-Setup-*.exe` 和 `InvoiceHub-windows-x64-*.zip`，避免文档与实际 asset 名称不一致。

公开仓库必须包含：

- `LICENSE`
- `THIRD_PARTY_NOTICES.md`
- `.github/CODEOWNERS`
- `README.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `licenses/LGPL-3.0.txt`
- `licenses/GPL-3.0.txt`
- `docs/user-quickstart.md`
- `docs/privacy-and-feedback.md`
- `docs/privacy-data-flow.md`
- `docs/release-checklist.md`
- `docs/pyside6-license-compliance.md`

公开仓库不得包含：

- `AGENTS.md`
- `desktop_app_design.md`
- `implementation_plan.md`
- `docs/minimum-mvp-gap.md`
- `docs/public-private-code-boundary.md`
- `private/`
- `runtime/`
- `exports/`
- `build/`
- `dist/`
- `config.json`
- `.env`、`.env.local`、`.npmrc`、`.pypirc`、`credentials.json`、`secrets.json`
- `*.pem`、`*.key`、`*.p12`、`*.pfx`
- 真实样本、数据库、导出包、安装包或压缩包。

## License 与第三方声明

- 仓库根目录必须包含 Apache-2.0 `LICENSE`。
- 仓库根目录必须包含 `THIRD_PARTY_NOTICES.md`。
- 仓库必须包含 `licenses/LGPL-3.0.txt` 和 `licenses/GPL-3.0.txt`，用于 PySide6 / Qt 相关许可文本随包分发。
- `CONTRIBUTING.md` 必须说明 DCO / `Signed-off-by` 提交流程。
- PySide6 / Qt 使用范围必须与 `docs/pyside6-license-compliance.md` 一致。

## Windows 发布包

Windows 发布包必须包含：

- `LICENSE`
- `THIRD_PARTY_NOTICES.md`
- `licenses/LGPL-3.0.txt`
- `licenses/GPL-3.0.txt`

发布包检查：

- 生成 portable zip。
- 生成 Inno Setup 安装包。
- 生成 `checksums.txt`，覆盖 portable zip 和 setup exe。
- 安装包默认 per-user 安装，不要求管理员权限。
- 用户数据写入 AppData，不写入安装目录。
- 卸载默认不删除用户 runtime 数据。
- 安装包和 portable zip 不包含 `runtime/invoices.db`、`config.json`、真实附件、导出包、`ms-playwright/` 或 `chromium-*`。
- 发布后记录 package validation result，覆盖 checksum、普通安装、普通用户权限安装、静默安装、启动、静默卸载、portable 解压和 portable 启动。

## Windows package / winget readiness

- Confirm installer and portable zip asset names.
- Confirm `checksums.txt` includes all release assets.
- Confirm README and release notes reference the same asset names.
- Confirm Inno Setup silent install switches before winget submission.
- Do not submit winget manifest until v0.1.2 or later release is validated.
- Do not use GitHub Packages for Windows desktop app distribution unless a future package ecosystem requires it.

## GitHub 设置

这些是仓库设置项，需要在 GitHub UI 中手动确认：

- 启用 private vulnerability reporting。
- 启用 secret scanning 和 push protection。
- 保护 `master` 分支，要求 PR 和 CI 通过后才能合并。
- `.github/workflows/`、`packaging/`、`SECURITY.md`、隐私文档变更需要维护者 review。
- Release workflow 默认 `contents: read`，只有发布 job 使用 `contents: write`。

## Windows 空环境冒烟

在一台干净 Windows 环境验证：

- 安装包可完成安装并启动。
- portable zip 解压后可启动。
- 系统没有 Chrome 时，浏览器自动化优先使用 Microsoft Edge。
- 首次启动没有乱码标题或乱码按钮。
- 本地导入、扫描邮箱配置入口、扫码上传入口、审核、保存、导出入口可见。
- 日志区收起后不占用大块空白，展开后日志可读。
- 打开日志目录、复制诊断信息、导出脱敏诊断包、打开 GitHub Issues 可用。

## 发布前人工结论

发布前记录：

- 是否使用真实数据：否。
- 是否上传用户附件、邮件正文、PDF 文本、数据库或 Excel：否。
- 是否通过公开导出检查：是 / 否。
- 是否通过 Windows 空环境冒烟：是 / 否。
- 是否确认 release artifacts 的 SHA256：是 / 否。
