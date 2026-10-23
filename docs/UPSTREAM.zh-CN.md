# 通过固定发布版本加载上游检查引擎

模板维护 CI 按[唯一版本文件](../tools/upstream/osv-scanner.json)下载、校验并运行
[Google 官方 OSV-Scanner](https://github.com/google/osv-scanner)。
扫描器读取本仓工具依赖锁，再查询 OSV 漏洞数据库作匹配。本仓不复制上游解析或漏洞判断代码；
这是固定发布资产的加载，不是 `uses:` 或 `workflow_call`。

```text
validate.yml / Template checks
  → 读取版本文件，下载官方 Linux amd64 发布资产并校验固定 SHA256
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

扫描工作流仅使用 `contents: read`，不上传 SARIF，不需要 GitHub Dependency graph、Security
写权限或额外 secret。PR、main push、merge_group 和手动维护运行均执行此检查。调用方原有
npm/pnpm/uv 审计保持各自用途；模板工具审计不代替业务测试、构建或应用依赖审计。

## 固定版本与验证

实际生效版本以[版本文件](../tools/upstream/osv-scanner.json)为准；以下为初次接入时的验证记录。

发布资产为
[osv-scanner_linux_amd64](https://github.com/google/osv-scanner/releases/download/v2.7.0/osv-scanner_linux_amd64)，
SHA256 为 `160c6253e2922e9e0a6a9771c5c4c40a4b3c6090b34a3cdd5e80c96cc2e4218b`。
该值与官方 [SHA256SUMS](https://github.com/google/osv-scanner/releases/download/v2.7.0/osv-scanner_SHA256SUMS)、
GitHub release 资产 digest、本地下载文件校验一致。版本输出为 scanner 2.7.0、scalibr 0.5.3。

本地在线实测：两份工具锁识别 16 个依赖条目，未报告漏洞，退出 0。另对 npm、pnpm、workspace、
uv.lock 和 uv requirements 五个 fixture 锁作只读核验，识别 6 个条目、退出 0；这不表示维护
步骤默认扫描了这些 fixtures。独立负例 `urllib3==1.26.5` 检出漏洞并退出 1，缺失锁退出 127。
远端是否通过以对应提交 Checks 为准。

OSV 数据持续更新，即使锁和引擎版本不变，新公开漏洞仍可能使后续运行失败。漏洞规则在扫描时直接查询，不复制到本仓；引擎的固定版本与 SHA256 则通过下述 PR 流程更新。

## 每周自动检查并提出更新 PR

[更新工作流](../.github/workflows/update-upstream.yml)安排在**每周一 UTC+8 12:00**（cron `0 4 * * 1`，UTC 04:00），也支持手动运行；自动更新实现或版本文件合入 main 时会立即执行一次。GitHub 定时任务可能排队延后，cron 不是精确到秒的执行保证。

只读检查 job 查询 Google 官方最新稳定发布，交叉核对 release asset digest 与官方 SHA256SUMS，拒绝预发布、降级、同版本内容改变、缺少资产或哈希冲突。新版本写入独立 JSON 后，复用维护 CI 的下载、实际二进制校验、版本核对和两锁扫描。没有新版时仍执行扫描并记录结果，不创建空 PR。

仅候选验证成功且版本变化时，独立发布 job 才获得 `contents: write`、`pull-requests: write` 和 `actions: write`。它只提交版本文件，以 `automation/osv-scanner-v<版本>` 分支创建或复用更新 PR；已有分支内容冲突时失败，不覆盖人工改动。随后显式派发该分支的完整 Template validation，不依赖机器人 PR 事件的审批状态。PR 不会自动合并；新的大版本也必须通过相同接口及扫描验证。

仓库的 **Settings → Actions → General → Workflow permissions → Allow GitHub Actions to create and approve pull requests** 必须允许机器人创建 PR。若仓库禁用该功能，创建步骤明确失败并提示设置位置，不冒充更新已经提交；没有新版的成功运行仅证明抓取和扫描，不能证明创建 PR 的权限已验收。无需添加个人访问令牌。

核心逻辑与离线负例测试位于 [tools/upstream](../tools/upstream/osv.py)，覆盖不可信发布元数据、下载校验、空/缺失扫描结果以及发布错误。实际执行结果以相应 Actions run 和更新 PR 的 Checks 为准。

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
