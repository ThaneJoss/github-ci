# github-ci：直接引用，按标准元数据自动识别

把下面文件保存为调用仓库的 `.github/workflows/ci.yml`。默认入口没有必填 inputs，不需要新增环境变量、secret 或专属配置文件。

```yaml
name: CI
'on':
  push: {}
  pull_request: {}
  merge_group: {}
  workflow_dispatch: {}
permissions:
  contents: read
jobs:
  ci:
    uses: ThaneJoss/github-ci/.github/workflows/ci.yml@main
```

GitHub 仍需要这个 caller 文件、基础权限，以及仓库自身正常的 manifest/锁/测试。模板不会凭空生成测试或豁免漏洞。

默认使用 `@main`：本仓库的更新合入 `main` 后，调用仓库下一次新触发会解析当时 `main` 的最新提交，无需再逐个修改 caller SHA。模板更新本身不会触发调用仓库，也不会替换正在运行的版本。选择此模式表示接受模板更新对后续运行的影响；需要可重复版本或临时回滚时可显式固定已验证的完整 SHA，但固定后不会自动跟随。不要创建同名 `main` tag，因为 GitHub 对同名 tag 的解析优先于分支。参见 [GitHub 引用规则](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows#calling-a-reusable-workflow)。

已有 run 的重跑与新触发不同：仅重跑失败 job 或单个 job 会沿用首次尝试的模板提交；重跑全部 jobs 会重新解析指定引用。需要验证模板最新版本时，建议新触发一次运行。参见 [GitHub 重跑规则](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations#behavior-of-reusable-workflows-when-re-running-jobs)。

自动读取 Node/Python 标准版本声明、npm/pnpm 锁、Node workspace、`package.json` 的检查 scripts、`pyproject.toml`/`uv.lock` 和受支持的测试约定。零依赖 JS＋Python 标准库项目免依赖安装；纯文档做离线检查。摘要逐项区分成功、失败和 **NOT RUN**，没有测试不写成测试通过。完整优先级、回退和错误见[自动识别契约](docs/AUTOMATIC.zh-CN.md)。

配置与辅助源码同样需要实际检查：JSON/JSONC、TOML、dotenv、XML、静态 `_headers`、Gitignore 规则和空 `.nojekyll` 按格式校验；Shell 只解析语法，非标准文件名的显式 ES 模块交给 Node 静态检查。SQL 目前只支持有标准方言依据的 SQLite 静态解析，不执行迁移、不连接数据库。格式失败不会被项目脚本覆盖，未知源码继续拒绝；[格式支持边界](docs/AUTOMATIC.zh-CN.md#文件格式与辅助源码)说明工具、依据及限制。

入口内置取消旧 run、超时和严格 `Gate`；通常一个 Quality runner 安装一次，再用一个短 Gate runner 汇总。首次成功运行后，按 GitHub 实际显示的 `ci / Gate` 名称设置 required check，并确认没有同名工作流。不要给 caller 的 `ci` job 加条件跳过，也不要用顶层 paths 过滤 required workflow。

特殊系统依赖可加一个可选 input，例如 `with: {system-packages: 7zip-standalone}`。特殊检查、版本矩阵、多独立根目录和 wheel 安装验证仍需项目明确表达，不能自动猜测。原有 `profile: node/python/docs` 与独立模块保留为显式接口；五个显式接入 examples 同样默认使用 `@main`，自动模式仍优先使用 [auto 示例](examples/auto.yml)，不要求复制 helper。

模板只按能力判断，不读取 owner/repo/项目名称；参见[可移植性契约](docs/PORTABILITY.zh-CN.md)。`@main` 是对自有共享 CI 入口的跟随策略；官方及第三方 Actions 仍固定完整 SHA，须审阅后更新，不随之改成浮动引用。内部相对 `uses: ./.github/workflows/...` 始终解析为入口选中的同一提交；自动运行时代码直接内嵌在该版本的 workflow 中，不执行 caller 的同名模板文件，也不额外从 `main` 下载脚本。调用方代码只在无 secret、contents:read 的 GitHub 托管 runner 上运行。

[验证记录与边界](docs/VALIDATION.zh-CN.md) · [设计、安全及成本依据](docs/DESIGN.zh-CN.md) · [完整 caller 文件](examples/auto.yml)
