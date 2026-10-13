# 自动识别契约

## 主路径和结果含义

默认 profile=auto；所有 inputs 可省略。入口执行 checkout → 只读发现 → 运行时准备 → 一次冻结安装 → 检查/审计 → Gate。发现本身不执行项目配置文件。摘要显示每项执行结果、版本选择来源和缺失的 lint/type/test/build。

quality-passed=true 表示本次计划中的检查和原生审计全部成功，**不表示项目有测试、满足全部产品需求或部署验收完成**。tests=not-run 表示没有测试执行；command-passed-count-unknown 只证明声明的测试命令退出成功，不伪造测试数；executed 来自受支持的真实 runner。语法检查和文档验证从不计为测试。

## 支持矩阵与优先级

| 标准元数据/结构 | 自动行为 | 歧义或限制 |
| --- | --- | --- |
| 根 package.json + package-lock.json/npm-shrinkwrap.json | npm ci，随后 npm audit --audit-level=high | 两份 Node 锁同时存在直接失败 |
| 根 package.json + pnpm-lock.yaml | pnpm frozen install 和 high/critical 审计 | packageManager 与锁冲突失败 |
| packageManager | npm/pnpm 精确 x.y.z 优先（允许标准 SHA 完整性后缀） | yarn/bun/浮动工具版本不支持 |
| 未声明 packageManager 版本 | npm 使用所选 Node 内置 npm；pnpm lock 9.0 固定回退 10.18.3，6.0 回退 8.15.9 | lock 格式不能证明原精确工具版本；未知格式报错。摘要显示回退 |
| Node 版本 | 可选 input → .nvmrc → .node-version → volta.node → engines.node → **24** | 稳定数字/semver 范围；lts/node 别名不支持。所选实际版本必须满足所有读到的声明，冲突失败 |
| npm workspaces / pnpm-workspace.yaml packages | 只从已提交 manifests 选成员，在根安装一次；执行根和每个成员的约定 scripts | 没有 root manifest、成员不在 workspace、成员独立锁或包管理器冲突均报错 |
| 无依赖 JS/plugin | 检查已提交 JS 语法，运行已声明脚本或标准 node:test 文件；不安装无意义依赖 | 任一 dependencies/dev/optional/peerDependencies 存在即要求锁 |
| Python 版本 | 可选 input → .python-version → project.requires-python → **3.13** | 保留 patch 下限与上限，例如 >=3.14.5,<3.15；不退回 3.11。将稳定 PEP 440 比较、逗号交集、==/!= 通配和 ~= 转成 setup-python 所需 semver；实际解释器还校验 requires-python |
| pyproject.toml + uv.lock | 固定 uv 0.12.19，uv export --locked 预检、uv sync --locked、uv audit --locked | 不把 uv.lock 当 pip requirements，不改写锁、不自动 uv lock |
| PEP 735 dependency-groups.ci | 存在时选择 --only-group ci，含 include-group | 此组只决定轻量测试环境，不暗示完整应用依赖已安装。无 ci 组用 project＋uv 默认组，不自动装 extras |
| 已选择的 Python依赖 | 声明 ruff 则运行 ruff check；mypy 同时有配置才运行 | 不临时下载未声明 linter/typechecker |
| pytest | 已选择依赖声明 pytest，且有根或 test/tests 下的 test_*.py/*_test.py | 只运行跟踪到的文件；真实 JUnit 必须非空，无失败/skip |
| unittest | 上述标准测试文件明确 import unittest/from unittest import | 至少一个 test case；失败或任何 skip 均失败 |
| Python 标准库脚本 | 用所选 Python 做语法检查；支持上述 unittest | 不凭 build.py、train.py、CLI 名称猜测要执行的任务 |
| 同根 JS + Python | 分别发现两个运行时与检查，共享一次 job | 例如标准 package build script 可明确调用 Python 打包 |
| 纯 Markdown/JSON | UTF-8/JSON 语法与支持的普通 Markdown 本地文件链接 | 不验证锚点、外链、wiki links 或站点生成；不算测试 |

未声明运行时版本时才用默认值；版本范围由 setup-node/setup-python 选取可用版本，范围本身不是精确 patch 锁。已存在的版本兼容矩阵不会从旧 workflow 自动复制，也不应因使用本入口而删除；需要多版本时保留 caller 的 matrix，用可选 node-version/python-version 传入每个版本。不同 runtime input 会区分并发取消组。

pnpm workspace YAML 支持常见字面 block 列表或带引号的 inline 列表，路径 glob 支持 *、** 和 ! 排除，不支持 YAML 锚点/标签。* 不跨目录。共享锁成员顺序检查，根脚本已递归执行时可能有重复；模板不猜根脚本覆盖了哪些成员。

## Node 脚本选择

每种能力按顺序选首个存在的名称：

| 能力 | 优先级 |
| --- | --- |
| lint | lint:ci → lint |
| typecheck | typecheck:ci → typecheck → type-check → check-types |
| test | test:ci → test → test:unit |
| build | build:ci → build |

不把 check/start/dev/prepare 任意脚本视为测试。没有 test script 时，只对 *.test.js/*.test.mjs/*.test.cjs（同样支持 .spec）中明确导入 node:test 的文件使用 Node 内置 runner；其余情况显示 NOT RUN。Node 内置 runner 必须报告非零测试数，不允许已识别的 skip/todo。其他测试 runner 仅证明命令成功；如需严格计数/skip 策略，用项目自己的 CI script 明确保证。

所有 JS 语法检查只针对跟踪文件；TypeScript/JSX/Vue 至少需要声明 lint/typecheck/build，不能以 node --check 冒充。Vue 项目应在标准 typecheck script 使用 vue-tsc；模板不能把缺失的 Vue 检查说成已有。

安装禁用 lifecycle scripts，运行检查禁用自动 pre/post hooks，避免因安装/测试顺带发布。依赖需要 native postinstall 时使用经过审阅的显式模式或项目 CI command。auto 拒绝选中脚本中直接的 deploy/publish/release/train/download/curl/wget、占位测试、--passWithNoTests、--if-present、|| true；允许 wrangler deploy --dry-run。会检查字面 npm/pnpm run 引用的脚本。**这只是直接误配置拦截，无法静态证明任意脚本内部安全**；项目自己的 CI scripts 仍应只做本地、轻量检查，不能连接生产或下载大数据。

## uv、CPU和系统工具

uv 原生锁保留不动。sync 使用 --no-build --no-install-project：仅安装锁中可用 wheel，不临时构建第三方 sdist，不构建/安装本地项目。wheel 内容、隔离安装、src-layout 可导入性与 CLI 行为需要项目现有明确测试或可选命令，摘要会显示打包验证未自动执行。

预检选中依赖后，拒绝 GPU 标识依赖、单包最大锁定 wheel 超过 100 MiB、保守总量超过 500 MiB、缺少 size/wheel，以及直接 URL/VCS/本地依赖。不自动切 CPU 源或删 CUDA 依赖，不要求重做整份锁；可复用已有标准 ci dependency-group。上限取选中包锁中最大的 wheel，跨平台包可能保守拒绝。uv audit 检查完整锁的已知漏洞；即使轻量组排除了某些运行时依赖，也不默认豁免完整锁。漏洞或审计服务错误都失败。

不存在通用标准能可靠说明 pytest 需要 7zz、数据库、浏览器或 GPU；模板不会猜 runner 已有这些工具。可选 system-packages 接受 Ubuntu 包名（可带版本），例如 7zip-standalone；apt 只重试一次，调用代码不获得云凭据。缺工具应失败；已识别的 skip 也失败。模板内部设置常见模型库离线变量，但这不是所有网络下载的通用沙箱。

## 明确不支持的自动结构

独立多根/多锁 monorepo、uv workspace、动态 Python metadata、非 registry Python依赖、纯 pip/Poetry/Pipenv/Yarn/Bun/其他语言构建系统、过大的数据/依赖、符号链接/子模块、超出声明的 Node workspace成员，都会报错或要求显式流程，不退化成 docs 绿灯。

只枚举 git ls-files，不递归磁盘查找；最多 20000 跟踪路径，单个读取文件最多 8 MiB。忽略 node_modules/.venv/vendor/dist/build/coverage 等安装及生成目录。遇到超过范围的结构，可以为独立根显式传 working-directory；各根必须有自己的真实锁。不要为避开错误删除已有必要检查。

无法可靠自动判断产品功能的“必要覆盖”、脚本是否包含远程副作用、系统工具、wheel 验收、CPU/GPU语义或旧 CI 矩阵意图。主路径不引入专属配置文件；少数特殊需求使用已有脚本/标准元数据，或保留显式接口。根 requirements*.txt 暂要求显式模式，即使同时有 uv.lock 也不猜两者的权威关系。

## 可选逃生接口

auto 支持 working-directory、timeout-minutes（1–45，默认15）、node-version、python-version、system-packages，以及 lint/typecheck/test/build/integration/browser-command、project-install-command。显式命令覆盖同种自动能力，仍然接受直接危险操作检查；Python 虚拟环境在执行检查时加入 PATH。project-install-command 在检查前执行，建议明确使用 .venv/bin/python 和 --no-deps --no-build-isolation。

lockfile/package-manager/package-manager-version/audit-command/docs-command/lightweight-node-version 属于旧显式模式，auto 不默默忽略它们。需要这些接口时指定 profile: node/python/docs；旧独立模块的默认 Node22/Python3.11 保持兼容，**自动模式的默认值不同**。旧 hash-pip 模块不是 uv 兼容接口；不支持的 uv 结构应保留已有原生 uv workflow，不需要手工重做 pip 锁。

## 精确版本、安全与成本

auto.yml 由 tools/auto/runtime.py + workflow.yml.in 生成；CI 强制逐字比对。被引用 workflow 本身携带脚本，使用隔离模式 Python 和 runner temp 路径；不会从 caller 的 tools/auto/runtime.py 加载、不会用 github.workflow_ref 猜 callee、不会从 main 下载。相对嵌套 uses 由 GitHub 解析为同一个提交。标准 actions 固定 40 位 SHA，工具下载仍依赖其上游分发与网络，不能把 pin 声称为完整供应链审计。

最小 contents:read、persist-credentials:false、无必填 secrets、不 secrets:inherit、不 pull_request_target、不部署/发布。自动模式不上传失败 artifacts，避免将 caller 的日志、数据、隐藏文件或凭据误打包；仅输出检查摘要。不要把凭据写进项目检查日志。全部取消后 GitHub 可能不再派发 Gate，取消状态不能算成功，新的 head 必须有新成功 Gate。

取消组由入口内置，包含 caller workflow、事件、PR/ref、工作目录、artifact-key及 runtime inputs。同 run 同目录的多个调用应使用不同 artifact-key；不要在 caller 使用同一个 reusable-ci 前缀的同组以免自取消。

默认每次调用一个 Quality runner＋一个2分钟上限的 Gate runner。共享 workspace 安装一次，顺序检查节约安装/派发成本；不声称并行必然更便宜。独立锁可由 caller matrix 并行，每个根都有 checkout/setup/install/Gate 成本，需要按关键路径、runner秒和账单规则测量后选 max-parallel。模板维护 fixtures 并行上限3只用于模板验证，不替代项目兼容矩阵。缓存只保存下载/store，键含 OS、架构、实际运行时、管理器版本和锁哈希，不复用 node_modules/.venv 作为安装成功证据；无性能倍数承诺。

参考：[GitHub reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)、[uv locking/syncing](https://docs.astral.sh/uv/concepts/projects/sync/)、[uv commands](https://docs.astral.sh/uv/reference/cli/)、[pnpm scripts](https://pnpm.io/cli/run)。
