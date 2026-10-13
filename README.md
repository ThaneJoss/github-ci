# github-ci：按能力复用的 CI

本仓库是 `ThaneJoss/github-ci` 的通用 CI 实现。发布与执行证据见[验证记录](docs/VALIDATION.zh-CN.md)。四个 `.github/workflows/*.yml` 是真正的 `workflow_call` 工作流。`examples/*.yml` 是调用方接入样例，已固定首次发布的真实模板commit；项目命令与依赖锁必须按调用方适配。不能把静态检查通过称为 GitHub 执行通过。

## 流程约束

这是按技术栈与能力配置的通用流程：不读取仓库身份、不维护项目白名单、不按用户项目名启用或豁免检查。调研清单不会成为运行时配置。见[可移植性契约](docs/PORTABILITY.zh-CN.md)。

## 接入

1. 示例固定模板commit `835d0365f1a05d53f1a3c49fa38d907ee3828093`；`ci.yml`通过相对`uses: ./.github/workflows/*.yml`引用同一commit的子工作流。升级时审阅并替换完整SHA。
2. 在调用仓库选择 `examples/web-npm.yml`、`worker-pnpm.yml`、`python-cpu.yml`、`docs.yml` 或零依赖插件的 `plugin-no-deps.yml`，复制为 `.github/workflows/ci.yml`，并只保留适用的真实检查命令。调用方命令执行在调用仓库的 checkout；不会自动获得模板仓库的脚本。
3. `docs.yml` 样例还需把 `examples/helpers/check_docs.py` 复制为调用仓库的 `.github/scripts/check_docs.py`。审计例外辅助工具如被选用，也需复制到调用仓库；默认 Node 门禁可直接使用包管理器 audit。
4. 首次实际运行验证之后，再把**唯一的 `Gate`** 设为 required check；本次交付没有修改任何分支保护。工作流显示名 `CI`、可复用 job 名 `CI` 不改变最终顶层 job 的 `name: Gate`。仓库内其他工作流不要复用 `Gate` 名称。

正常路径只有一个 `Quality` runner 加一个极短的调用方 `Gate` runner。模板不默认路径过滤、不排除 draft PR、不做部署、不发 bot 消息。若仓库无代码、无待验证内容或已退役，应暂不接入，不能为统一形式编造测试。

## 接口

入口：`.github/workflows/ci.yml`。无声明 secret、无 `secrets: inherit`、不需要 registry 或云平台凭据。调用方及模块都只授予 `contents: read`；门禁 job 权限为空。默认使用 GitHub.com 的 `ubuntu-24.04` 托管 runner。

| Input | 默认值/要求 | 用途 |
| --- | --- | --- |
| `profile` | 必填：`node` / `python` / `docs` | 只运行一个模块；无效值触发明确失败 |
| `working-directory` | `.` | 仓库内相对目录；禁止绝对路径、`..`、越界 symlink |
| `timeout-minutes` | `15`，整数 1–45 | Quality job 上限；caller Gate 另限 2 分钟 |
| `artifact-key` | `quality` | 1–64 位安全 slug；同 run 多次调用同模块时必须不同 |
| `lockfile` | Node/Python 必填，docs 不使用 | 相对 working-directory，必须已经提交 |
| `lint-command` / `typecheck-command` / `test-command` / `build-command` / `integration-command` | 空 | 仅执行适用检查，空项略过；Node/Python 至少填写一个实质检查 |
| `node-version` | `22` | 用项目支持的版本，可固定 patch；不自动扩矩阵 |
| `package-manager` | `npm` | 仅支持 `npm` 或 `pnpm` |
| `package-manager-version` | 空；pnpm 必须填精确 `x.y.z` | npm 空值使用 Node 自带版本；与 package.json 的 packageManager 声明和实际版本不一致就失败 |
| `browser-command` | 空 | Node 可选的必要浏览器冒烟/无障碍；浏览器安装由项目命令管理 |
| `python-version` | `3.11` | 用项目实际支持的 CPU 版本 |
| `project-install-command` | 空 | Python 可选本地项目安装；样例用 `--no-deps --no-build-isolation` |
| `audit-command` | Node 空值使用 npm/pnpm audit `--audit-level=high`；Python 必填 | 真正漏洞门禁；不得用 outdated 或 `|| true` 代替 |
| `docs-command` | docs 必填 | 项目适用的离线文档、清单、插件结构检查 |
| `lightweight-node-version` | 空 | 仅零依赖插件可选 Node 运行时；不安装依赖、不运行无锁 audit |

唯一 workflow output 为字符串 `quality-passed`：选中模块按顺序完成所有配置检查后才输出 `true`；调用方同时要求 `needs.ci.result == success`，避免只看输出而遗漏失败。独立调用 `node.yml` / `python.yml` / `docs.yml` 的输入是上表对应子集，可直接阅读每个文件的完整 `workflow_call.inputs`；其输出与入口一致。

`Gate` 使用 `if: always()`，只接受上游结果 `success` 且完成证明 `true`。上游失败、取消、整组被跳过、缺失完成证明都会失败；未选中的其他 profile 正常跳过不影响选中的模块。末尾另有 `if: cancelled()` 的明确失败步骤。整份 workflow 被人工取消时，GitHub 可能终止后续调度；模板不承诺这种情况下还能产出一个完成的 Gate，取消也不能当作成功证据。

默认没有路径优化：所有事件都会创建门禁，不会因为 `on.paths` 跳过整份 required workflow 而 pending。将来若加入路径规划，必须始终触发 workflow，由明确、可审计的计划输出决定“允许跳过”，门禁核对计划和结果；禁止直接把 `needs.ci.result == skipped` 设为成功。

## 安装、缓存与检查

Node 使用一次 `npm ci` 或 `pnpm install --frozen-lockfile`。锁文件必须位于 working-directory；monorepo 使用 workspace 根目录与根锁，检查命令再选择子包。配置先比对 package.json 的 `packageManager` 声明（识别版本后的 integrity 后缀）；安装后的实际包管理器版本再次校验，并禁用 pnpm 的自动版本切换。Vue 项目的 `typecheck` 应确实调用 `vue-tsc`；只用 `tsc` 不能证明 `.vue` SFC 已覆盖。

`setup-node` 自动缓存显式关闭。单独 `actions/cache` 仅缓存 npm 下载缓存或 pnpm store，不缓存 `node_modules`；完整 key 为 OS、arch、实际 Node 版本、包管理器名称与实际版本、锁 hash。restore prefix 仅放宽锁 hash，恢复后仍运行锁安装。

Python 使用新建 `.venv-ci`，安装 `pip --require-hashes --only-binary=:all: -r <lock>`，锁住全部 CPU 依赖、验证工具与构建后端。仅缓存 pip 下载缓存，key 为 OS、arch、实际 Python 版本与锁 hash；不缓存已安装环境。要求锁中依赖有相应 CPU wheels；缺 wheel 时先设计受控、锁定构建工具的例外，不自动回退未锁定 sdist 构建。GPU 不可见，HF Hub/datasets 设为离线；检查命令仍必须采用小型本地 fixtures，不能借此声称任意网络下载都被系统阻止。

只有安装步骤对已识别网络错误最多重试一次；工具自身的网络重试也设了有限上限。锁失配、lint、类型、测试、build、审计失败不重跑来制造绿色。各命令通过 env 传入 `bash -e -o pipefail -c`，不把表达式直接拼入脚本文本。调用方仍需保持命令本身忠实传播失败，模板无法挽救 `|| true` 或吞掉失败的项目脚本。

失败产物只在配置验证通过后收集已知目录：`ci-reports/`、`coverage/`、`test-results/`、`playwright-report/`，保留 7 天，忽略缺文件，不递归打包整个仓库；隐藏文件、`.env*`、credentials 文件、`.git`、依赖环境均排除。项目应只向这些目录写不含敏感数据的诊断文件。同一 run 调用两次同 profile 时，为两次调用提供不同 `artifact-key`。

`examples/helpers/check_docs.py` 仅用 Python 标准库离线校验显式选择的 Markdown/JSON 文件，包括 UTF-8、JSON 语法/重复 key，以及常见 inline/reference 相对文件链接。它不是完整 Markdown/Obsidian/站点解析器；不检验片段 anchor、站点根路由、外链可达性、wiki-links，也不伪装成单元测试。若这些属于项目契约，改用项目已有的对应检查。

纯文档默认不安装 Node。零依赖插件可设置 `lightweight-node-version`，执行实际 `node --test` 和清单/打包校验；若存在 package.json，则任何 dependencies、devDependencies、optionalDependencies 或 peerDependencies 声明都会拒绝这种轻量模式，需改用有锁的 Node profile。零依赖插件没有 npm 依赖可审计，不硬加会因缺锁报错的 npm audit；Node 运行时仍需按支持周期更新。

## 执行范围与升级

默认 PR 快速门禁按安装后 lint → type → unit → build → 轻集成 → 可选 browser → audit 顺序执行，复用同一次 checkout/install。没有证据前，不为每一步拆 runner。真正慢且独立的兼容矩阵、全量浏览器、较大 CPU 测试应放在独立 nightly/release 工作流，并以测得关键路径和 runner 成本决定是否调整；不在本模板启动 GPU 训练。

所有外部 Actions 固定完整 SHA，注释标明核验 tag/date。当前选取的版本使用 Node 24 Action 运行时；不直接适用于未升级 self-hosted 或 GitHub Enterprise Server，尤其 upload-artifact v4+ 的 GHES 限制需单独适配。最新 tag 不等于完成运行兼容验收。

调用方推荐固定模板完整 SHA，通过审阅升级 PR 更新。若维护 `v1` 浮动主版本标签，必须明确其可移动性与回滚政策；需要可复现或敏感门禁的仓库仍固定 SHA。公共模板只含通用逻辑；私有项目命令和路径留在各自调用仓库。模板只校验代码质量，不把预览构建/上传、真实预览 URL 可达、线上功能验收、生产发布当作同一个证据。

## 设计与验证记录

- [完整中文设计](docs/DESIGN.zh-CN.md)
- [Action SHA与官方来源](docs/action-pins.json)
- [验证记录与边界](docs/VALIDATION.zh-CN.md)

- [大型公开项目实践与采用理由](docs/INDUSTRY-PRACTICES.zh-CN.md)
- [不按项目身份分流的本地检查](tools/check_portability.py)

## 模板自身维护

`.github/workflows/validate.yml` 只检验本仓库的语法、helper、门禁真值表和可移植性，并通过本仓库相对`workflow_call`运行资料档冒烟。它不是调用项目的运行时模块，也不表示Node/Python或跨仓权限已经验收。维护环境是Linux x86_64、Python 3.12；PyYAML wheel使用哈希锁，actionlint下载校验固定SHA256。离线检查可运行`python tools/validate.py`、`python tools/test_helpers.py`和`python tools/test_portability.py`。
