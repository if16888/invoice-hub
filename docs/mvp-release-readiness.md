# MVP 发布前任务清单

本清单用于从 `invoice-hub-private` 准备公开 MVP。原则是：当前 private 仓继续作为内部开发仓；公开仓必须从 allowlist 导出的干净文件树做 clean initial commit。

## P0：首发阻断项

- [x] 选择开源许可证：使用 Apache-2.0。
- [x] 根目录提交 `LICENSE`。
- [x] 根目录提交 `THIRD_PARTY_NOTICES.md`。
- [x] CONTRIBUTING 增加 DCO sign-off 要求。
- [x] PySide6 许可文档与实际模块使用保持一致。
- [x] 增加 public export tree 检查脚本：`python scripts/check_public_export.py <public-tree>`。
- [ ] 从 `master` 用 allowlist 导出新的 public repo，不直接公开 private repo。
- [ ] public repo 启用 GitHub private vulnerability reporting。
- [ ] public repo 启用 secret scanning / push protection（如果仓库计划支持）。
- [ ] public repo 配置分支保护，要求测试和隐私扫描通过。

## P1：发布候选必须验收

- [ ] 私有仓 release gate：
  ```powershell
  python scripts/check_repo_privacy.py
  python -m scripts.invoice_fetch --help
  python -m unittest discover -v
  git diff --check
  ```
- [ ] public export tree gate：
  ```powershell
  python scripts/check_public_export.py <public-tree>
  python scripts/check_repo_privacy.py
  python -m scripts.invoice_fetch --help
  python -m unittest discover -v
  git diff --check
  ```
- [ ] Windows 空环境安装包冒烟：
  - 安装包不要求管理员权限。
  - 首次启动进入空状态引导。
  - 用户数据写入 `%APPDATA%\InvoiceHub\`。
  - 本地导入合成样本可入库。
  - 审核、保存、关联报销组、导出可完成。
  - 导出脱敏诊断包不含原始票据、数据库或完整 tokenized URL。
  - 卸载不删除用户 runtime 数据。
- [ ] 发布包 hygiene：
  - portable zip 与 setup exe 均生成。
  - `checksums.txt` 覆盖 setup exe 和 portable zip。
  - 解包后不包含 `runtime/`、`config.json`、`invoices.db`、真实附件、`ms-playwright/` 或 `chromium-*`。
  - 解包后包含 `LICENSE` 与 `THIRD_PARTY_NOTICES.md`。
- [ ] UI 截图验收：
  - 空状态。
  - 发票列表 + 原件预览。
  - 报销组导出 + 诊断反馈。
  - 底部日志不遮挡、不留大空白，按钮文字完整。

## P2：首发后排期

- [ ] Windows Defender 可选附件扫描或隔离机制。
- [ ] 100 / 500 / 2000 条发票的启动、搜索、导出性能基线。
- [ ] OpenSSF Best Practices baseline。
- [ ] 更完整的企业模板包、平台适配器和商业策略继续留在私有仓。

## Public Export Allowlist

公开仓建议只导出：

- `README.md`
- `LICENSE`
- `THIRD_PARTY_NOTICES.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `config.example.json`
- `requirements*.txt`
- `.github/`
- `docs/architecture.md`
- `docs/roadmap.md`
- `docs/user-quickstart.md`
- `docs/privacy-and-feedback.md`
- `docs/privacy-data-flow.md`
- `docs/generic-imap-mailboxes.md`
- `docs/known-issues.md`
- `docs/release-checklist.md`
- `docs/pyside6-license-compliance.md`
- `packaging/`
- `scripts/`
- `tests/`

不得导出：

- `AGENTS.md`
- `private/`
- `runtime/`
- `exports/`
- `build/`
- `dist/`
- `.worktrees/`
- `docs/superpowers/`
- `docs/minimum-mvp-gap.md`
- `docs/public-private-code-boundary.md`
- `desktop_app_design.md`
- `implementation_plan.md`
- `config.json`
- 真实票据、日志、数据库、邮箱导出、Excel 导出包或任何密钥。
