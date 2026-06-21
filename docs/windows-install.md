# Windows 下载与安装安全说明

Invoice Hub 的 Windows 发布包目前仍是未签名或低信誉的新构建，因此在第一次下载时，Windows 可能会显示这些提示：

- SmartScreen
- `Unknown Publisher`
- “不常见下载”或类似的下载信誉提示

这些提示不等于恶意软件。它们通常表示当前构建还没有积累足够的下载信誉，或者尚未配置可信的 Authenticode 代码签名和时间戳。

## 只从官方 Releases 下载

请只从官方 GitHub Releases 页面下载：

https://github.com/if16888/invoice-hub/releases

不要从第三方镜像、聊天附件、网盘转存链接或非官方重新打包的文件获取发布包。

## 核对 SHA256

每次发布都会提供 `SHA256SUMS.txt`。下载后，先用 PowerShell 核对文件哈希，再和清单里的值比对：

```powershell
Get-FileHash .\InvoiceHub-<version>-win64-setup.exe -Algorithm SHA256
Get-FileHash .\InvoiceHub-<version>-win64-portable.zip -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

`SHA256SUMS.txt` 应该同时列出 setup exe 和 portable zip。只有当你本地算出的 SHA256 和清单一致时，才继续安装或解压。

## MSI 不是关键

把发行包改成 MSI，并不会自动消除 SmartScreen，也不会自动带来可信发布者身份。对用户下载信誉真正关键的是：

1. 只通过官方 Releases 分发
2. 使用可信的 Authenticode 代码签名
3. 给签名加上时间戳，保留长期验证能力

正式推广前，优先把主程序和安装器都做成可验证、可时间戳的 Authenticode 签名，再考虑其他安装格式调整。
