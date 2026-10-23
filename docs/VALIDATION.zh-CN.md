# 验证记录与验收边界

## 结果证明与成员覆盖修复（2026-10-24）

修复 Node 连续命令中前一组失败、取消或空测试被后一组成功掩盖的问题；逐组验证完整 TAP/spec 结果，并记录真实测试数。修复 workspace 中一个成员的 lint/typecheck/build 被错误用作其他成员前端源码覆盖的问题；覆盖判定按最近 package 和 override 后实际计划执行。新增 18 项回归包含真实 Node TAP/spec 正反执行、嵌套 subtest、同级/嵌套成员、npm/pnpm 与 override 边界。

补充 integration/browser 的 NOT RUN 摘要及维护 CI 的 merge_group 触发；专项检查仍通过既有显式接口接入。维护 CI 下载固定版本、校验 SHA256 的 Google OSV Scanner 官方引擎，扫描本仓两份工具 requirements 锁；漏洞规则在执行时从 OSV 数据库加载，发现漏洞或扫描失败进入既有 checks/Gate。来源、扫描范围与更新边界见 [上游引用说明](UPSTREAM.zh-CN.md)。

本地验证：107 项自动回归、47 项 helper、33 项可移植性用例、171 项维护 Gate 情形和自动测试中的 76 项 Gate 情形通过；actionlint 1.7.12、生成一致性、文档离线链接及 diff 检查通过。六种真实 npm/pnpm launcher smoke 均通过，包含冻结安装、嵌套行为测试、原生审计、禁用 hooks、失败传播与锁不匹配拒绝。Node 24 在维护回归前显式设置，避免依赖 runner 默认 Node。

OSV Scanner v2.7.0 本地识别工具锁中的 16 个包条目并成功完成；额外扫描现有五份 npm/pnpm/workspace/uv fixture 锁识别 6 个包条目并通过。已知有漏洞的 urllib3 1.26.5 负例退出 1，指定不存在的锁退出 127；未使用忽略错误或漏洞豁免。固定二进制更新需重新核对来源、哈希并通过 CI，漏洞数据库无需复制到本仓。后续增加的周一更新工作流只提出版本 PR，仍须满足这些验证要求。

远端 fixtures 和上游扫描器的实际执行结果以本轮 [PR #5](https://github.com/ThaneJoss/github-ci/pull/5) 最新提交的 Checks 为准；这些验证不证明调用方原有浏览器、部署或安装验收已恢复。

## 自动入口的真实 GitHub 验证

自动入口首个全绿提交 [5445f5879fcb2dd07240490497e7b249715a73e2](https://github.com/ThaneJoss/github-ci/commit/5445f5879fcb2dd07240490497e7b249715a73e2) 的 [Template validation run 38351517899](https://github.com/ThaneJoss/github-ci/actions/runs/38351517899) 成功。9 类泛化 fixtures：npm、pnpm、零依赖 JS＋Python 标准库打包、Python/uv＋7zz、Python标准库、Python patch 下限、纯 docs、无测试命令、npm workspace。22 个实际派发 job 成功，其他未选 profile 为预期 skipped；runner 执行时间合计152秒，包含所有 fixture 和各 Gate，不是一个调用方的成本或实际账单，也不是加速倍数。

真实执行包含 npm ci/pnpm frozen install、包管理器原生审计、原生 uv export/sync/audit --locked、7zz 小归档验证、Python >=3.14.5,<3.15 选择及运行、JS/Python行为测试、无测试时的 NOT RUN 记录、同仓精确版本嵌套调用和稳定 Gate。文档/语法检查从不计为测试。uv 测试安装真实的小型锁定第三方 wheel，不转换成手写 pip hash 锁。

实际发现并修复了两类集成问题：setup-python 需要把 PEP 440 范围转换成 semver；7zz 所需包为 7zip-standalone，不能假定 7zip 包或 runner 自带满足测试。失败 run 的自动分支及汇总 Gate 都保持失败，未用忽略错误或跳过测试处理。

历史验证提交 `a02b1a7b15ddb68b5fc01b93995154ee2147d0a0` 包含当轮六项审查修复；对应 [Template validation run 39747738335](https://github.com/ThaneJoss/github-ci/actions/runs/39747738335) 已通过，55 项自动回归、47 项 helper 测试、33 项可移植性用例及 22 个实际执行 job 全部成功（40 个未选 profile job 按设计 skipped）；该轮最终 head 与全部检查的验收记录见 [PR #1](https://github.com/ThaneJoss/github-ci/pull/1) 的提交及 Checks。此 SHA 仅用于定位历史证据；当前 README 和示例默认使用 `@main`，后续版本须查看各自提交的 Checks，不能沿用旧 run 作为最新版本的通过证明。当轮记录时 PR 尚未合并，也未改业务仓库或分支保护。

## 回归覆盖

维护 CI 运行 actionlint、bash/Python 语法、自动 workflow 逐字生成校验、通用能力可移植性检查、原有47项审计/内容 helper 与33项可移植性用例，并执行自动识别回归：
- npm/pnpm选择、版本与锁冲突、缺锁、workspace范围与独立锁歧义；
- 陌生名称/更名结果一致，不查 owner/repo；
- 不递归 node_modules/生成目录，不读越界 symlink；caller json.py 不覆盖模板解释器；
- 约定脚本优先级、原生 node:test、拒绝直接发布/训练/下载及测试占位/错误吞没；
- Python精确 patch下限、PEP440范围转换、uv与pip导出共存、stdlib/pytest选择；
- 空测试、跳过、测试失败、审计失败及锁变化不能生成成功证明；
- 入口所有 inputs 无必填项；嵌入代码与源码一致。

PR 审查修复的回归由 unittest discovery 统一收集全部 tools/auto/test_*.py：逐成员原生测试回退、npm/pnpm workspace 元数据与实际管理器绑定、拒绝未校验的 packageManager 完整性哈希、带选项的嵌套脚本解析、包装脚本中的 node:test 空测试/skip 检查，以及混合项目的未知源码拒绝。远端 workspace fixture 同时包含有 test script 和无 test script 的成员。

Gate真值表覆盖 success/failure/cancelled/skipped/缺失输出，以及未选分支意外运行。它在 GitHub 上执行真实 Gate 脚本；这不等于对 GitHub 强制取消整个 run 的调度行为已做实测。

Actions 来源及固定 SHA 沿用 [action-pins.json](action-pins.json)。actionlint 1.7.12 下载校验固定 SHA256；PyYAML 通过 require-hashes 安装。未启用 ShellCheck，不宣称 bash -n 等于完整 shell 语义审计。

## pnpm 启动兼容回归

`python tools/auto/smoke_package_manager.py` 在临时目录中安装 Node 所带 npm 的同版本副本、npm 11.6.0、pnpm 8.15.9/10.18.3/12.4.2/12.14.0，读取实际 auto.yml 的安全环境设置，并以独立进程执行生产控制器的 detect/install/execute。每种版本验证冻结安装、嵌套 node:test、high/critical 审计、安装及 pre/post hooks 禁用、测试失败不完成、锁不匹配明确拒绝且原锁不变。旧 npm/pnpm 使用现有 fixture，pnpm 8/12 使用各版本实际生成并提交的原生锁。测试不修改宿主工具链；pnpm 启动器的备用下载在此 smoke 中关闭。

离线启动回归覆盖无 shebang shell、旧 shebang、原生 executable、特殊字符/空参数原样传递、非零退出、版本不符、版本查询/安装/脚本/审计完整调用路径、npm 直通及 Yarn 既有拒绝。CI 保留原有 fixtures 和 Gate，新增真实版本 smoke；最终 head 的远端结果以 PR Checks 为准。

这组回归证明 Ubuntu/Node 24 下的模板启动兼容和轻量冻结安装，不证明调用业务项目已经恢复；使用 `@main` 的调用方须新触发并完成自身检查，仍固定旧 SHA 的调用方须先更新引用。

## 通用格式识别回归（2026-10-22）

本轮以 main `4e1cb6ce1982c7a91b09f192b8f458a2c975563f` 为基线，保留 pnpm 启动兼容修复。新增独立 `formats` fixture，在任意目录放置 JSONC、dotenv、XML、_headers、Gitignore 规则、空标记、SQLite SQL、Shell 和非标准后缀 ES 模块；不复用真实业务源码作为 fixture。维护 CI 将该 fixture 与既有九类 fixture 一起通过相同自动入口执行。

本地执行通过：88 项自动回归、47 项 helper 测试、33 项可移植性用例、actionlint 1.7.12、171 项 workflow Gate 真值表与自动测试中的 76 项 Gate 用例、生成一致性、文档离线链接及 diff 检查。六种真实 npm/pnpm launcher smoke 均通过，包含冻结安装、嵌套测试、原生审计、禁用 hooks、失败传播及锁不匹配拒绝。独立格式 fixture 实跑 detect/install/execute，使用哈希锁定的独立工具环境，10 项检查成功且 tests=not-run；将 SQL 改为无效语法后，实际解析器子进程失败，完成标记保持 false。该环境已有 npm prefix 指向未提供 semver 的用户目录，端到端 harness 显式选用已安装 Node 的正确 prefix 后完成；没有据此修改模板的 Node 版本规则。

格式回归包含有效/无效输入、字符串中的 JSONC 注释标记、dotenv 不执行展开、XML 外部实体拒绝、Shell 不执行文件或启动脚本、模块语法错误及 Python 环境中的伪 Node 不遮蔽解析器、SQL 未知方言/目录范围/恶意配置/模板/错误吞没拒绝、真实解析器缺失与失败传播、多 workspace 成员，以及超过五项未知源码的完整诊断。原有未知源码测试中的不支持 Shell 样例改为 fish；sh/bash 由新的正反语法用例覆盖，不把其语法通过当成执行通过。

以下仅为只读兼容验收集，未写入这些仓库分支。每个临时副本重新 fetch PR head 后执行 discovery、所有格式校验和已发现的 JS/Python 原生语法检查，全部通过；应用 scripts、测试、构建和项目依赖审计未执行，不能据此合并调用方 PR 或声称应用 CI 已绿。模板实现、工具配置与合成测试不含这些项目的名字、目录白名单或豁免。

| 只读 PR | 验收 head | 格式文件数 |
| --- | --- | --- |
| [title2doi #3](https://github.com/ThaneJoss/title2doi/pull/3) | `3423111216542cc61f87649c302c83c551efafb5` | 9 |
| [cloudflare-speed-test #3](https://github.com/ThaneJoss/cloudflare-speed-test/pull/3) | `a0f7b8988a54210a660b493d0acdf3cbacc501ac` | 9 |
| [flowmaster #20](https://github.com/ThaneJoss/flowmaster/pull/20) | `8b296d4eb3cb389bae8b38316516a2f608df0191` | 12 |
| [epub #6](https://github.com/ThaneJoss/epub/pull/6) | `38c8bdc176bcc89016d2e5461db89dfb1a7554de` | 6 |
| [fast #22](https://github.com/ThaneJoss/fast/pull/22) | `31848816c078805f27d7848e95033c612dbdf6cc` | 13 |
| [file-transfer #48](https://github.com/ThaneJoss/file-transfer/pull/48) | `8bb322b71e06546caf707cb2eaec39030cf6a2dc` | 20 |
| [webapps #120](https://github.com/ThaneJoss/webapps/pull/120) | `daf713af23401f7701ea637754463e2b107f2add` | 10 |
| [cloudflare-usage-guard #18](https://github.com/ThaneJoss/cloudflare-usage-guard/pull/18) | `a49aaaf2af7faef9b0ad49e69710b8faa1f0060d` | 17 |

完整扫描纠正了日志中的类型假设：验收集内域名文件名的六个文件实际为 ES 模块，不是 IP/hosts 数据。它们通过通用内容特征选择 Node 模块语法检查；没有按域名或所在目录识别。SQL 合计九个文件，均位于标准 D1 配置声明的迁移范围。该验收不额外宣称支持任意名称的 hosts 数据、未声明方言 SQL、其他 Shell/数据库方言或所有模块格式；准确边界见[格式契约](AUTOMATIC.zh-CN.md#文件格式与辅助源码)。远端 CI 和 bot 审查以此修复 PR 的最终 head Checks 为准，本记录不预先声称远端已通过。

## 未测与不可代替的边界

未创建外部 caller 仓库，也未改业务项目，因此**跨仓调用、fork权限、旧多版本/多系统矩阵等价性、真实科研/应用覆盖、GPU训练、云平台、浏览器/部署验收、私有registry和整个run中途取消**未验收。自动模式的失败产物策略是不上传，不假称完成了各种第三方报告脱敏。

没有因为一个轻量 fixture 成功就声称所有项目已兼容。Python源代码检查不证明wheel正确；node命令退出成功也不能证明未知runner执行了多少测试。CPU组选取和大依赖限制见[自动识别契约](AUTOMATIC.zh-CN.md)。原有13-job或兼容矩阵需原样保留，直到项目自行证明覆盖等价后再改；本 PR 没有删减这些项目的检查。

## 首次显式模块发布（历史证据）

初始提交 [835d0365f1a05d53f1a3c49fa38d907ee3828093](https://github.com/ThaneJoss/github-ci/commit/835d0365f1a05d53f1a3c49fa38d907ee3828093) 的 [run 38344010586](https://github.com/ThaneJoss/github-ci/actions/runs/38344010586) 验证了显式 docs 嵌套调用成功路径。五个显式 caller examples 当时固定此提交，现已默认使用 `@main`；该历史 run 不是当前示例或自动入口的完整实测证据。行业来源、设计、安全和成本讨论继续保留在对应文档中。
