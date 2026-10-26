# Microsoft Store MSIX packaging

Invoice Hub keeps the existing PyInstaller `onedir` payload as the application
runtime and adds MSIX only as a distribution wrapper for Microsoft Store.

The migration is deliberately additive:

```text
Python / PySide6
  -> PyInstaller onedir
     -> Inno Setup / GitHub Release    (existing fallback during migration)
     -> MSIX / Microsoft Store         (consumer-facing target)
```

Do not remove the Inno Setup path until a Store package has passed certification,
clean install, upgrade, application workflow, and uninstall acceptance on real
Windows systems.

## Store identity authority

The following values are **not repository constants** and must be copied exactly
from the app identity page in Microsoft Partner Center after the app name has
been reserved:

- Package/Identity/Name
- Package/Identity/Publisher
- Publisher display name
- Reserved app display name

Identity values are case-sensitive. Do not invent, normalize, or commit fake
production values to the manifest template.

The manual `Windows Store MSIX` workflow accepts those values as dispatch inputs,
stages the real frozen payload, generates `AppxManifest.xml`, creates required
logo assets, and invokes the Windows SDK `MakeAppx` tool.

The workflow only uploads a Store-submission build artifact to GitHub Actions.
It does **not** publish to Microsoft Store and does not create a GitHub Release.

## Version boundary

Invoice Hub user-visible versioning remains SemVer, for example:

```text
APP_VERSION = v0.2.0
```

Microsoft Store package identity uses a four-part numeric version. Store rules
require a non-zero first component and reserve the fourth component as `0`.
Invoice Hub therefore uses a deterministic mapping:

```text
source X.Y.Z -> Store package (X + 1).Y.Z.0
```

Examples:

```text
0.1.8 -> 1.1.8.0
0.1.9 -> 1.1.9.0
0.2.0 -> 1.2.0.0
1.0.0 -> 2.0.0.0
```

The Store package version is an installation/update identity. It does not
replace the product-facing Invoice Hub version shown in the application.

Prerelease suffixes such as `0.2.0-rc3` are not accepted by the Store packaging
script. RC packages remain on the existing GitHub test-distribution path.

## Desktop execution model

The generated package is a full-trust packaged desktop application:

- architecture: `x64`
- executable: `InvoiceHub.exe`
- entry point: `Windows.FullTrustApplication`
- capability: `runFullTrust`
- device family: `Windows.Desktop`

This preserves the existing PySide6/Win32 desktop application model; it is not
a conversion to UWP or WinUI.

## Runtime data

The frozen application already keeps runtime state under the user's application
data location rather than the installation directory. MSIX acceptance must
still explicitly verify that configuration, SQLite data, logs, keyring-backed
secrets, downloaded materials, and exports retain their intended behavior.

## Release acceptance before Store submission

A `MakeAppx` success is packaging evidence, not product acceptance. Before the
Store becomes the recommended stable channel, validate the generated Store
package on real Windows for:

1. clean installation and first launch;
2. application version identity;
3. mailbox configuration and credential persistence;
4. local import and invoice review;
5. PDF/OFD/material preview paths used by the current product;
6. opening attachments and export directories through the Windows shell;
7. claim-group complete export;
8. application upgrade while preserving existing runtime data;
9. uninstall behavior and the explicitly chosen user-data retention policy;
10. Windows App Certification / Partner Center certification.

The Store channel must not be declared the stable consumer authority until these
checks pass on the exact candidate intended for submission.

## Signing boundary

The MSIX artifact produced by this workflow is intended for **Microsoft Store
submission**, not broad direct sideload distribution. Store identity values must
match Partner Center. Microsoft Store certification/republication provides the
Store distribution trust chain.

If Invoice Hub later distributes an MSIX directly outside Microsoft Store, that
is a separate release model and requires its own trusted package-signing policy.
Likewise, a directly downloaded Inno Setup executable remains subject to the
existing Windows Authenticode/SmartScreen trust considerations.

## 启动证据边界

Store 打包工作流在 MakeAppx 前启动的是未安装的 onedir EXE，因此使用与便携版一致的冷启动门槛（默认 6000 ms，`portable_startup_ms`）。这不是已安装 Store 应用的启动结果。

已安装 Store 应用仍需满足默认 3000 ms 的验收目标（`strict_startup_ms`）。流水线摘要明确记录该项 `NOT RUN`；只有取得签名包并完成实际 MSIX 安装后才可验证并用于发布决策。打包成功不表示 Store 安装、升级、卸载、权限审批或启动验收完成。

诊断记录：master 18304be 的未安装 EXE 首次 Paint 为 4669 ms，原工作流使用 3000 ms 因而失败；该失败记录保留。启动探针继续从 Qt 初始化前计时到完整主窗口首次 Paint，不扣除冷初始化开销；新增阶段时序仅用于诊断，不参与放宽或重算总耗时。
