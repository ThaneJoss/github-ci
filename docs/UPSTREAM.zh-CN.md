# 通过固定发布版本加载上游检查引擎

模板维护 CI 下载、校验并运行 Google 官方
[OSV-Scanner v2.7.0](https://github.com/google/osv-scanner/releases/tag/v2.7.0)。
扫描器读取本仓工具依赖锁，再查询 OSV 漏洞数据库作匹配。本仓不复制上游解析或漏洞判断代码；
这是固定发布资产的加载，不是 `uses:` 或 `workflow_call`。

```text
validate.yml / Template checks
  → 下载官方 v2.7.0 Linux amd64 发布资产并校验固定 SHA256
  → OSV-Scanner 读取两份工具锁并查询 OSV 数据库
  → 成功退出 + 非空、完整的扫描结果
  → Template checks 结果 → 最终 Gate
```

[维护工作流](../.github/workflows/validate.yml)在 checkout 后扫描
`tools/requirements-ci.txt` 和 `tools/auto/requirements-formats.txt`，显式指定 `requirements.txt`
解析器，避免非标准文件名漏扫。禁用调用图分析与依赖补全，不安装项目依赖，不执行项目脚本。
工具只读取明确指定的锁；不声称该维护步骤扫描了全部业务仓库、fixtures 或未知格式。

扫描使用空的显式配置，不载入项目漏洞忽略规则；`--all-vulns` 保留全部报告漏洞，不以严重性
阈值、跳过或 `continue-on-error` 放行。漏洞、输入错误、下载/校验失败、扫描超时及 API 请求
失败均中断步骤。下载设置连接与总时限，扫描限时 120 秒，整个步骤限时 5 分钟。
成功退出后还校验 JSON 必须恰好覆盖两份锁，且每份至少识别一个依赖；空结果不能证明通过。

工作流仍仅使用 `contents: read`，不上传 SARIF，不需要 GitHub Dependency graph、Security
写权限或额外 secret。PR、main push、merge_group 和手动维护运行均执行此检查。调用方原有
npm/pnpm/uv 审计保持各自用途；模板工具审计不代替业务测试、构建或应用依赖审计。

## 固定版本与验证

发布资产为
[osv-scanner_linux_amd64](https://github.com/google/osv-scanner/releases/download/v2.7.0/osv-scanner_linux_amd64)，
SHA256 为 `160c6253e2922e9e0a6a9771c5c4c40a4b3c6090b34a3cdd5e80c96cc2e4218b`。
该值与官方 [SHA256SUMS](https://github.com/google/osv-scanner/releases/download/v2.7.0/osv-scanner_SHA256SUMS)、
GitHub release 资产 digest、本地下载文件校验一致。版本输出为 scanner 2.7.0、scalibr 0.5.3。

本地在线实测：两份工具锁识别 16 个依赖条目，未报告漏洞，退出 0。另对 npm、pnpm、workspace、
uv.lock 和 uv requirements 五个 fixture 锁作只读核验，识别 6 个条目、退出 0；这不表示维护
步骤默认扫描了这些 fixtures。独立负例 `urllib3==1.26.5` 检出漏洞并退出 1，缺失锁退出 127。
远端是否通过以对应提交 Checks 为准。

OSV 数据持续更新，即使锁和引擎版本不变，新公开漏洞仍可能使后续运行失败。当前不自动升级
扫描器；升级须同时更新固定版本及可信 SHA256，重跑真实锁、漏洞负例、非空结果校验和模板
检查。不能只改下载 URL 或将最新版本默认当成兼容版本。

## 三个参考项目为何不能直接作为通用工作流调用

[行业来源清单](industry-sources.json)中的项目是工程设计参考，不是本仓运行时继承的通用规则包。
本次接口核对使用下列固定提交：

| 来源 | 实际接口 | 不能直接套用的原因 |
| --- | --- | --- |
| [Microsoft Playwright](https://github.com/microsoft/playwright/tree/b8f2857ed102174de8a46f0bb18a3e7beb422997/.github/workflows) | tests_primary / tests_secondary 没有 workflow_call | 专用 runner、Playwright 测试及内部 Actions；run-test 还引用工作区中的报告 Actions |
| [Cloudflare Workers SDK](https://github.com/cloudflare/workers-sdk/blob/e651d7c0dd8e171dcc1820679f9f46601971d876/.github/workflows/test-and-check.yml) | test-and-check 没有 workflow_call | 依赖 monorepo 目录、内部安装 Action、Turbo 配置和组织服务 |
| [Vercel Next.js](https://github.com/vercel/next.js/blob/8b583887cee277dd7036bcfdfeafbd1d6e37fc59/.github/workflows/build_reusable.yml) | build_reusable 有 workflow_call，stepName 必填 | 内部脚本、Next 原生构建、默认 runner 和测试布局都属于 Next.js 自身源码 |

后续增加上游规则时，应选择有公共接口的 Action、reusable workflow、CLI 或规则包，确认输入、
权限、环境、退出状态与版本，再包装进本仓稳定接口并验证失败传播。上游发布权限、专用 runner
和业务测试命令不能自动成为本项目规则。

OSV 的 CLI、锁格式和结果接口见
[使用文档](https://github.com/google/osv-scanner/blob/v2.7.0/docs/usage.md)、
[指定锁文件](https://github.com/google/osv-scanner/blob/v2.7.0/docs/scan-source.md)和
[JSON 格式](https://github.com/google/osv-scanner/blob/v2.7.0/docs/output.md)。
