# Windows 安全分发与签名准备设计

## 目标

在不切换 MSI、不改变用户数据目录且不引入任何私有证书的前提下，继续使用 PyInstaller onedir 与 Inno Setup，稳定生成 Windows 安装版、便携版和 SHA256 校验文件，并为未来 Authenticode 签名预留可选入口。

## 发布产物

版本来源保持为 `scripts.invoice_fetch.version.VERSION`。Git tag 继续使用 `v<version>`，发布文件名使用不带 `v` 的纯版本号：

- `InvoiceHub-<version>-win64-setup.exe`
- `InvoiceHub-<version>-win64-portable.zip`
- `SHA256SUMS.txt`

`SHA256SUMS.txt` 使用常见的 `<lowercase-sha256><two spaces><filename>` 格式，并覆盖同一次发布产生的 setup exe 和 portable zip。

## PyInstaller 与版本资源

继续使用 `packaging/invoice_hub_windows.spec` 的 onedir 结构：`EXE` 设置 `exclude_binaries=True`，最终由 `COLLECT` 生成 `dist/InvoiceHub/`。`EXE` 和 `COLLECT` 均保持 `upx=False`。

构建前由一个小型 Python 脚本从唯一版本源生成 PyInstaller Windows version resource 文件，避免在 spec、CI 和应用代码中分别维护版本号。稳定字段为：

- `ProductName`: `Invoice Hub`
- `CompanyName`: `Invoice Hub`
- `FileDescription`: `Invoice Hub`
- `InternalName`: `InvoiceHub`
- `OriginalFilename`: `InvoiceHub.exe`
- `ProductVersion` / `FileVersion`: 当前纯版本号

`CompanyName` 在没有正式法人品牌要求时保持产品发布者名称。未来证书主体可以使用真实个人或组织身份；二者不需要现在强行伪装成同一字符串。

## 可选 Authenticode 签名

新增 `scripts/sign_windows.ps1`，接受一个或多个文件路径，并读取：

- `SIGNTOOL_PATH`: `signtool.exe` 路径
- `CERT_SUBJECT`: Windows 证书存储中的证书主题
- `TIMESTAMP_URL`: RFC 3161 时间戳地址

缺少 `SIGNTOOL_PATH` 或 `CERT_SUBJECT` 时，脚本打印明确 warning 并以成功状态退出，使无证书的本地构建和当前 CI 不受阻塞。配置签名时使用 SHA-256 文件摘要和 SHA-256 时间戳摘要；签名命令失败则返回失败状态，避免发布伪装成已签名文件。

未来启用签名时，顺序为：

1. PyInstaller 构建完成后签署 `dist/InvoiceHub/InvoiceHub.exe`。
2. 使用已签名的 onedir 目录生成 portable zip。
3. Inno Setup 生成 setup exe。
4. 签署最终 setup exe。
5. 最后计算两个发布产物的 SHA256。

Inno Setup 脚本增加条件式 `SignTool` 设置，仅当构建调用方显式定义签名工具名称时启用。默认构建不要求签名，不改变现有 per-user 安装、安装目录、卸载行为或用户数据目录。

## CI 数据流

Windows release workflow 保持现有测试、隐私检查、源码检查、PyInstaller 构建、启动检查和 Inno Setup 构建顺序。发布阶段统一使用纯版本号命名，并执行：

1. 生成版本资源。
2. 构建 onedir。
3. 调用可选签名脚本处理主程序；当前无证书时仅 warning。
4. 创建 portable zip。
5. 构建 Inno Setup 安装器。
6. 调用可选签名脚本处理安装器。
7. 生成 `SHA256SUMS.txt`。
8. 验证并上传三个产物。

GitHub Actions artifact 和 GitHub Release 均上传 setup exe、portable zip 和 `SHA256SUMS.txt`。CI 不保存、生成或请求 PFX、私钥、token 或其他签名秘密。

## 用户安全文档

新增 `docs/windows-install.md` 并由 README 的 Windows 下载区链接。文档说明：

- 未签名或尚未积累下载信誉的新版本可能出现 SmartScreen、“Unknown Publisher”或“不常见下载”提示；这不等价于恶意软件，也不是安全保证。
- 只从项目官方 GitHub Releases 页面下载。
- 使用 PowerShell `Get-FileHash -Algorithm SHA256` 核对文件，并与 `SHA256SUMS.txt` 中对应文件名的值比较。
- SHA256 只能证明下载内容与发布清单一致，不能替代发布者身份验证。
- MSI 只是安装包格式，不会天然消除 SmartScreen。正式推广前，优先为主程序和安装器配置可信的 Authenticode 代码签名及时间戳。

README 中的示例文件名同步为新命名，但不回改历史 release notes。

## 测试与验收

先更新现有 packaging 测试，使其针对新约定失败，再逐项实现：

- spec 明确为 onedir、禁用 UPX并引用版本资源。
- 版本资源生成器输出稳定字段和来自唯一版本源的版本号。
- 无证书环境运行签名脚本时打印 warning、返回成功且不修改目标文件。
- Inno Setup 的签名配置为条件式，默认不强制。
- workflow 使用三个准确产物名、正确签名顺序并上传全部产物。
- Windows 安全文档包含官方来源、SmartScreen、SHA256、MSI 与 Authenticode 说明。

最终运行针对性 packaging 测试、完整 unittest、`compileall`、仓库隐私门禁、公开导出门禁和 `git diff --check`。测试产生的本地 `runtime/` 数据在最终公开导出门禁前清理，但不删除用户已有数据。

## 非目标

- 不切换或新增 MSI。
- 不购买、生成或提交证书。
- 不提交 PFX、私钥、token 或证书密码。
- 不改变 `%APPDATA%\InvoiceHub\` 等用户数据位置。
- 不重构应用业务逻辑或安装卸载语义。
