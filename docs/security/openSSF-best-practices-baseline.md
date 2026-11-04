# OpenSSF Best Practices baseline（v0.2.0）

> 本文是 2026-11-04 对仓库现状与 OpenSSF Best Practices 基线标准的对照记录。
> 它不表示已经获得 OpenSSF badge，也不替代 GitHub 安全设置或发布验收。

## 结论

- 基础治理、漏洞报告、CI 门禁、依赖管理和构建证据已经具备。
- 主要缺口：发布产物签名、覆盖率/模糊测试、分支保护的持续验证，以及正式提交 OpenSSF badge 申请。
- 仓库已公开；private vulnerability reporting 已启用。

## 对照

| 主题 | 现状 | 证据 / 说明 |
|---|---|---|
| 公开项目主页与文档 | 满足 | README、docs/、user quickstart、安装说明 |
| 开源许可证 | 满足 | Apache-2.0 `LICENSE` + `THIRD_PARTY_NOTICES.md` |
| 安全策略 | 满足 | `SECURITY.md`；私密漏洞报告已启用 |
| 漏洞报告渠道 | 满足 | GitHub private vulnerability reporting；`SECURITY.md` 说明私密渠道 |
| 代码评审 | 满足 | 所有变更经 PR；禁止直接修改 master |
| CI 必需门禁 | 满足 | Source gates、3 个 unit shard、HCI acceptance |
| Exact-master 构建证据 | 满足 | `Exact-master CI attestation` 要求 master 树与成功 PR CI 完全一致 |
| 依赖漏洞管理 | 满足 | Dependabot、`pip-audit` PR 门禁、lock 闭包测试、忽略规则 |
| 依赖可复现性 | 部分满足 | 四份 pip-compile lock；尚无 hash/universal lock（见 known limitations） |
| GitHub Actions 供应链 | 满足 | 所有 `uses:` 固定到 commit SHA，并有策略测试 |
| 发布产物校验和 | 满足 | Windows 审计生成 `SHA256SUMS.txt` |
| 发布产物签名 | 缺口 | 当前无 Authenticode 签名；SmartScreen 提示已在 known issues 记录 |
| SBOM | 部分满足 | GitHub Dependency Graph 提供 SBOM；未在发布包内附 SBOM |
| 测试 | 满足 | 单元/HCI/GUI/真实浏览器 SSRF 回归；未统计覆盖率 |
| 静态分析 / 模糊测试 | 缺口 | 有 compileall/隐私/架构策略，但没有专门的 SAST 或 fuzzing |
| 分支保护 / secret scanning | 待管理员确认 | 当前 token 无法读取完整仓库安全设置 |
| 发布说明与已知限制 | 满足 | `docs/release-notes/`、`docs/known-issues.md` |
| 事件响应 | 部分满足 | `SECURITY.md` 提供私密报告；无正式响应时限 SLA |

## 建议的后续动作

1. 由仓库管理员确认并记录分支保护、secret scanning / push protection 状态。
2. 评估 Authenticode 签名（至少对 setup exe 和 portable exe），或在 release notes 中继续明确未签名边界。
3. 在发布包中附带 Dependency Graph SBOM，或生成 CycloneDX/SPDX 文件。
4. 引入覆盖率统计与至少一项 SAST（例如 `ruff`/`bandit`）作为非阻断基线，再逐步收紧。
5. 满足条件后再提交 OpenSSF Best Practices badge 申请。
