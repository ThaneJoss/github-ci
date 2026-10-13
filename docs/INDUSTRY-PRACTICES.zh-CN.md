# 从大型公开项目提炼的 CI 实践

检索与只读核验：2026-10-13 UTC 03:40–03:47。实际读取了 Microsoft Playwright、Cloudflare Workers SDK、Vercel Next.js 的14份工作流/辅助实现/工程说明，以及GitHub与Playwright官方文档。下面描述的是固定提交中的公开工程，**不代表这些公司的全部内部CI，也不表示已经执行或认证它们的配置**。源文件清单、commit/blob SHA、读取时间和SHA256见[industry-sources.json](industry-sources.json)。

学习目标是通用流程，不复制公司或业务项目名单。第三方项目名仅用于准确归属研究来源；本模板不会据这些名称、调用仓库名称或组织身份分流。

## 1. 变更范围：在流程内判定，未知时保守执行

Next.js的主workflow先执行`changes`，将文档/编译器范围判断输出给后续job；实际辅助脚本在没有检测到变化时仍执行检查命令。这是“先可靠判定、再减少工作”的实例。[主workflow](https://github.com/vercel/next.js/blob/f10699476a2655fbf562849c64cc132ac2036b8c/.github/workflows/build_and_test.yml#L34)、[实际diff与回退实现](https://github.com/vercel/next.js/blob/f10699476a2655fbf562849c64cc132ac2036b8c/scripts/run-for-change.mjs#L174)

Workers SDK在已经触发的job内用路径结果控制安装和测试步骤。[路径检测与安装条件](https://github.com/cloudflare/workers-sdk/blob/1787b353ddb35c9d82a6a7fdae8bc4dc2f4cd035/.github/workflows/test-and-check.yml#L151)

**采用的原则：** 若后续引入优化，路径/依赖规则由调用方按能力声明，diff错误、分页不完整、共享配置/锁变化时执行；最终Gate验证明确计划。**当前不采用自动路径优化：** 对约一分钟的流程，额外选择job、diff依赖和维护成本可能不划算。也不复制上游具体目录表或Playwright主workflow的顶层`paths-ignore`作为required入口；GitHub说明整个required workflow被路径过滤时可能Pending。[官方说明](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks#handling-skipped-but-required-checks)

## 2. 并行和矩阵：根据关键路径，而不是任务名数量

Playwright主CI给部分Linux/macOS测试使用两片及`58:42`权重，Windows使用三片及`44:33:23`；它没有机械地给所有环境相同分片数。[主CI矩阵](https://github.com/microsoft/playwright/blob/a3401cfe0dcf317101572d025fa46248d0779b42/.github/workflows/tests_primary.yml#L65)

但其复合Action每次调用仍执行npm安装、构建和浏览器准备，所以分片不是免费加速。[实际run-test Action](https://github.com/microsoft/playwright/blob/a3401cfe0dcf317101572d025fa46248d0779b42/.github/actions/run-test/action.yml)

Workers SDK也按OS/测试域分别安排分片，让某些长测试独立启动；其工程说明解释了耗时估计和保留覆盖的理由。[分片工程说明](https://github.com/cloudflare/workers-sdk/blob/1787b353ddb35c9d82a6a7fdae8bc4dc2f4cd035/.github/workflows/README.md#L47)

**采用：** 量化每分支setup/install/测试/收尾与等待，优先消除长尾，矩阵只包含真实支持边界。**不照搬：** 多系统×浏览器×运行时×分片的乘积、小任务独立runner、大型专用runner。默认仍是一个安装环境加一个Gate；兼容扩展放独立定时/手动层。官方Playwright CI建议从受控worker数开始；分片报告可合并，但合并job还需下载、安装和运行合并工具。[CI建议](https://playwright.dev/docs/ci#workers)、[合并分片报告](https://playwright.dev/docs/test-sharding#merging-reports-from-multiple-shards)

## 3. 构建复用：区分产物、下载缓存和测试结果缓存

Next.js的复用workflow以OS/架构推导原生目标，先下载同一run上游产物；下载失败可以走真实重建。生产者上传带目标架构的二进制，短期保留。**这只说明原生产物可以复用，不证明全项目永远只build一次**：同文件仍有JavaScript构建命令，结果还受Turbo缓存影响。[下载、回退重建和上传](https://github.com/vercel/next.js/blob/f10699476a2655fbf562849c64cc132ac2036b8c/.github/workflows/build_reusable.yml#L330)

同一文件的pnpm store缓存区分OS/架构/锁，并说明避免缓存不完整安装；另有以run/attempt为边界的已通过测试列表缓存。这两种缓存用途不同。[依赖缓存](https://github.com/vercel/next.js/blob/f10699476a2655fbf562849c64cc132ac2036b8c/.github/workflows/build_reusable.yml#L385)、[测试结果缓存](https://github.com/vercel/next.js/blob/f10699476a2655fbf562849c64cc132ac2036b8c/.github/workflows/build_reusable.yml#L448)

**采用：** 包下载缓存配合锁安装；若昂贵构建确有多个消费者，再用同run、同SHA、显式OS/架构的产物，验证下载成功和内容。**不默认采用：** 为数秒构建增加上传/下载与依赖调度；跨提交直接复用“测试通过”；带组织凭据的远程缓存。本模板核心检查失败不重跑，cache命中也不跳过锁安装。

浏览器缓存也不是统一答案：Workers SDK只有检测到安装完成标记才保存其特定Chrome缓存；Playwright官方通常不建议缓存浏览器二进制，因为恢复可能与下载相当，且系统依赖仍需安装。两者服务于不同工程，不能互相代替。[完整安装条件](https://github.com/cloudflare/workers-sdk/blob/1787b353ddb35c9d82a6a7fdae8bc4dc2f4cd035/.github/workflows/test-and-check.yml#L296)、[官方缓存说明](https://playwright.dev/docs/ci#caching-browsers)

## 4. 可复用接口与稳定结果门禁

Next.js的入口反复调用独立`workflow_call`构建文件；它的聚合job显式列出多个上游，注释提醒遗漏祖先依赖可能把下游skip误当通过。其规则接受项目计划内skip，同时拒绝failure/cancelled。[复用接口](https://github.com/vercel/next.js/blob/f10699476a2655fbf562849c64cc132ac2036b8c/.github/workflows/build_reusable.yml#L1)、[聚合依赖和判定](https://github.com/vercel/next.js/blob/f10699476a2655fbf562849c64cc132ac2036b8c/.github/workflows/build_and_test.yml#L1241)

Workers SDK为了不改变已有保护规则，保留旧的结果名称，让它们等待分片，并只接受success。[兼容门禁](https://github.com/cloudflare/workers-sdk/blob/1787b353ddb35c9d82a6a7fdae8bc4dc2f4cd035/.github/workflows/test-and-check.yml#L344)

**采用：** 将内部job拆合与对外required check名称解耦。**本模板的具体规则：** 一个固定caller `Gate`，必须同时收到success和完成证明；选中模块unexpected skip一律失败。不会复制上游多个历史兼容门禁、组织定制check名或项目特例。GitHub复用权限与checkout上下文仍按官方规则处理。[官方复用说明](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)

## 5. Flake和重试：保留首次失败，而不是无限重跑

Workers SDK工程说明将框架内部retry、job重跑、断言轮询区分，并记录成功/耗尽重试及耗时；明确报告可能不完整。Playwright官方也区分首次通过、重试后通过和最终失败。[重试诊断说明](https://github.com/cloudflare/workers-sdk/blob/1787b353ddb35c9d82a6a7fdae8bc4dc2f4cd035/.github/workflows/README.md#L60)、[Playwright retries](https://playwright.dev/docs/test-retries)

**采用：** 超时、清理、有限等待、报告原始失败。模板仅对可识别安装网络错误最多重试一次。浏览器稳定性首先用隔离fixture、事件/状态等待修复；默认不额外包一层测试重跑。确需诊断性重试时由调用方明确设置上限并保留首次失败/trace，将flaky数量单独报告，不能把它写成首次全绿；严格门禁可按测试工具已验证的能力让flake阻断。**不采用：** retry-until-green、隐藏核心失败的`continue-on-error`、跨run复用通过记录来掩盖回归。

## 6. 权限和发布：学隔离边界，不复制组织特权

Playwright的发布workflow单独使用OIDC；Next.js的发布入口是独立定时/手动流程；Workers SDK预览文件明确说明它只部署、不执行测试。[Playwright发布](https://github.com/microsoft/playwright/blob/a3401cfe0dcf317101572d025fa46248d0779b42/.github/workflows/publish_release.yml)、[Next.js发布](https://github.com/vercel/next.js/blob/f10699476a2655fbf562849c64cc132ac2036b8c/.github/workflows/trigger_release.yml)、[Workers SDK预览](https://github.com/cloudflare/workers-sdk/blob/1787b353ddb35c9d82a6a7fdae8bc4dc2f4cd035/.github/workflows/deploy-previews.yml#L1)

这些上游流程包含组织身份条件、远程凭据或项目标签，它们属于上游自己的信任策略，**不进入本模板**。本模板只保留无secret质量验证、`contents: read`、不持久化checkout凭据、参数经env传入、Actions完整SHA、独立部署边界。上游安全工程说明也强调这些基本原则，但不是复制任何特权事件的授权。[Workers SDK安全说明](https://github.com/cloudflare/workers-sdk/blob/1787b353ddb35c9d82a6a7fdae8bc4dc2f4cd035/.github/workflows/README.md#L7)

## 对当前候选的实际影响

本轮保持9份运行时/调用方YAML不变：它们已经没有仓库身份分流、已有能力inputs、稳定Gate、锁安装与最小权限。新增[可移植性契约](PORTABILITY.zh-CN.md)及本地检查脚本；补充以上采用/不采用理由。没有为了与大仓库外观相似而加入paths选择job、大矩阵、远程缓存secret、发布job或测试结果缓存。

后续评估只比较同等覆盖下的P50/P95墙钟、runner秒、冷暖缓存、flake和定位成本；不得从上游配置或一次样本推算固定加速倍数。本轮重新进行本地静态验证，并增加独立的模板维护CI；发布后运行证据及尚未覆盖的能力见[验证记录](VALIDATION.zh-CN.md)。
