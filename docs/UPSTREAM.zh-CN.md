# 通过引用加载上游实现

模板维护 CI 现在直接引用 GitHub 官方的
[actions/dependency-review-action v5.0.0](https://github.com/actions/dependency-review-action/tree/a1d282b36b6f3519aa1f3fc636f609c47dddb294)，
固定完整提交 SHA。GitHub Actions 在运行时下载并执行该提交提供的检查引擎；本仓不复制它的实现代码。

加载链为：

```text
github-ci 的 Pull Request
  → validate.yml / Template checks
  → 官方 dependency-review-action@固定 SHA
  → 读取本仓 .github/dependency-review.yml
  → 检查 GitHub 依赖图识别的新增依赖漏洞
  → Template checks 结果
  → 最终 Gate
```

[维护工作流](../.github/workflows/validate.yml)在 checkout 后执行此检查。
[声明式策略](../.github/dependency-review.yml)由本仓维护：对 runtime、development、unknown
三个依赖范围中的 high/critical 漏洞阻断；不将问题降级为警告，不发 PR 评论，不检查许可证，
也不增加令牌权限。检查使用现有 `contents: read`，失败会使 Template checks 和最终 Gate 失败。
这里引用的是 GitHub 的检查引擎，阈值与范围是本仓策略，不能称为继承了 GitHub 的全部内部规则。

该步骤只在本模板仓库的 `pull_request` 运行；push、merge_group 和手动运行继续执行维护检查与
fixtures，但不将跳过的依赖差异检查记为执行成功。它检查的是 GitHub 依赖图可识别的差异，
不是全量依赖安装、完整漏洞审计或业务测试；调用方现有的 npm/pnpm/uv 审计仍有各自用途。
它也不会自动添加到所有使用 `ci.yml` 的业务仓库。官方 Action 的私有仓库支持要求 GitHub
Advanced Security，不能未经能力确认就将其变为所有调用方的默认必需步骤。

## 上游更新如何生效

[Dependabot 配置](../.github/dependabot.yml)每周检查一次，仅允许更新
`actions/dependency-review-action` 的引用。新版本通过 PR 提议；固定 SHA 在审查和维护 CI 通过后
更新，不启用自动合并，也不使用浮动版本在每次运行时静默换引擎。

这个范围是有意限制的：其他 Actions 同时存在于生成的 `auto.yml` 与
`tools/auto/workflow.yml.in`，只更新生成文件会破坏一致性。将来扩大自动更新范围，应先加入
源模板更新和重新生成流程，再运行生成一致性、actionlint、自动回归、Gate 真值表及实际 fixtures。
当前配置不自动更新这些双源引用，也不替代包管理器锁文件的更新流程。

## 三个参考项目为何不能直接作为通用工作流调用

[行业来源清单](industry-sources.json)记录的三个项目是工程设计参考，不是本仓运行时继承的通用规则包。
本次接口核对使用下列固定提交：

| 来源 | 实际接口 | 不能直接套用的原因 |
| --- | --- | --- |
| [Microsoft Playwright](https://github.com/microsoft/playwright/tree/b8f2857ed102174de8a46f0bb18a3e7beb422997/.github/workflows) | tests_primary / tests_secondary 没有 workflow_call | 使用专用 runner、Playwright 自身测试和内部 Actions；run-test composite 还引用调用方工作区内的报告 Actions |
| [Cloudflare Workers SDK](https://github.com/cloudflare/workers-sdk/blob/e651d7c0dd8e171dcc1820679f9f46601971d876/.github/workflows/test-and-check.yml) | test-and-check 没有 workflow_call | 依赖 monorepo 目录、内部安装 Action、Turbo 配置及组织服务 |
| [Vercel Next.js](https://github.com/vercel/next.js/blob/8b583887cee277dd7036bcfdfeafbd1d6e37fc59/.github/workflows/build_reusable.yml) | build_reusable 有 workflow_call，stepName 必填 | 内部脚本、Next.js 原生构建、默认 runner 和测试布局属于 Next.js 自身源码，不是任意应用的构建接口 |

因此，不能仅把这些文件放进 `uses:` 就宣称加载了大公司的 CI 规则。后续扩展应选择明确提供
跨仓公共接口的 Action、reusable workflow 或规则包，逐项确认输入、权限、运行环境、退出状态与
依赖版本，再包装进本仓稳定接口并验证失败传播。

GitHub 官方 Action 本身也支持 `config-file: OWNER/REPOSITORY/PATH@REF` 引用外部声明式策略。
若将来把本仓策略提供给多个仓库，可使用该接口并固定策略提交；目前维护工作流读取本仓本次
checkout 的配置，保证策略修改随同一个 PR 参与审查。规则文件不能替代相应引擎，也不能把其他
项目的任意 YAML、组织权限或测试命令自动解释为本项目适用的规则。

接口与执行约束见官方
[Action 定义](https://github.com/actions/dependency-review-action/blob/a1d282b36b6f3519aa1f3fc636f609c47dddb294/action.yml)、
[配置解析](https://github.com/actions/dependency-review-action/blob/a1d282b36b6f3519aa1f3fc636f609c47dddb294/src/config.ts)和
[使用说明](https://github.com/actions/dependency-review-action/blob/a1d282b36b6f3519aa1f3fc636f609c47dddb294/README.md)。
