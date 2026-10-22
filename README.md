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
    uses: ThaneJoss/github-ci/.github/workflows/ci.yml@a02b1a7b15ddb68b5fc01b93995154ee2147d0a0
```

GitHub 仍需要这个 caller 文件、基础权限，以及仓库自身正常的 manifest/锁/测试。模板不会凭空生成测试或豁免漏洞。升级时审阅并更换完整 SHA；此 PR 未合并，固定提交仍可引用。

自动读取 Node/Python 标准版本声明、npm/pnpm 锁、Node workspace、`package.json` 的检查 scripts、`pyproject.toml`/`uv.lock` 和受支持的测试约定。零依赖 JS＋Python 标准库项目免依赖安装；纯文档做离线检查。摘要逐项区分成功、失败和 **NOT RUN**，没有测试不写成测试通过。完整优先级、回退和错误见[自动识别契约](docs/AUTOMATIC.zh-CN.md)。

入口内置取消旧 run、超时和严格 `Gate`；通常一个 Quality runner 安装一次，再用一个短 Gate runner 汇总。首次成功运行后，按 GitHub 实际显示的 `ci / Gate` 名称设置 required check，并确认没有同名工作流。不要给 caller 的 `ci` job 加条件跳过，也不要用顶层 paths 过滤 required workflow。

特殊系统依赖可加一个可选 input，例如 `with: {system-packages: 7zip-standalone}`。特殊检查、版本矩阵、多独立根目录和 wheel 安装验证仍需项目明确表达，不能自动猜测。原有 `profile: node/python/docs` 与独立模块保留为显式接口；原五个 examples 是旧版显式接入示例，不是新的主路径，也不要求自动模式复制 helper。

模板只按能力判断，不读取 owner/repo/项目名称；参见[可移植性契约](docs/PORTABILITY.zh-CN.md)。Actions 固定 SHA，嵌套 workflow 固定同一版本，自动运行时代码直接内嵌在被调用的 workflow 中，不执行 caller 的同名模板文件，也不追踪 main 下载脚本。调用方代码只在无 secret、contents:read 的 GitHub 托管 runner 上运行。

[验证记录与边界](docs/VALIDATION.zh-CN.md) · [设计、安全及成本依据](docs/DESIGN.zh-CN.md) · [完整 caller 文件](examples/auto.yml)
