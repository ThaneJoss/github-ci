# 验证记录与验收边界

## 自动入口的真实 GitHub 验证

自动入口首个全绿提交 [5445f5879fcb2dd07240490497e7b249715a73e2](https://github.com/ThaneJoss/github-ci/commit/5445f5879fcb2dd07240490497e7b249715a73e2) 的 [Template validation run 38351517899](https://github.com/ThaneJoss/github-ci/actions/runs/38351517899) 成功。9 类泛化 fixtures：npm、pnpm、零依赖 JS＋Python 标准库打包、Python/uv＋7zz、Python标准库、Python patch 下限、纯 docs、无测试命令、npm workspace。22 个实际派发 job 成功，其他未选 profile 为预期 skipped；runner 执行时间合计152秒，包含所有 fixture 和各 Gate，不是一个调用方的成本或实际账单，也不是加速倍数。

真实执行包含 npm ci/pnpm frozen install、包管理器原生审计、原生 uv export/sync/audit --locked、7zz 小归档验证、Python >=3.14.5,<3.15 选择及运行、JS/Python行为测试、无测试时的 NOT RUN 记录、同仓精确版本嵌套调用和稳定 Gate。文档/语法检查从不计为测试。uv 测试安装真实的小型锁定第三方 wheel，不转换成手写 pip hash 锁。

实际发现并修复了两类集成问题：setup-python 需要把 PEP 440 范围转换成 semver；7zz 所需包为 7zip-standalone，不能假定 7zip 包或 runner 自带满足测试。失败 run 的自动分支及汇总 Gate 都保持失败，未用忽略错误或跳过测试处理。

本版示例固定的运行时代码提交为 `ae3905e0f5782edd68b2f201f42b075b55941013`，增加原生 uv.lock 优先于根 requirements*.txt 导出文件的支持；最终 head 与全部检查的验收记录放在 [draft PR #1](https://github.com/ThaneJoss/github-ci/pull/1)，避免在 commit 中循环引用自身 SHA。PR 未合并，没有改业务仓库或分支保护。

## 回归覆盖

维护 CI 运行 actionlint、bash/Python 语法、自动 workflow 逐字生成校验、通用能力可移植性检查、原有47项审计/内容 helper 与33项可移植性用例，并执行自动识别回归：
- npm/pnpm选择、版本与锁冲突、缺锁、workspace范围与独立锁歧义；
- 陌生名称/更名结果一致，不查 owner/repo；
- 不递归 node_modules/生成目录，不读越界 symlink；caller json.py 不覆盖模板解释器；
- 约定脚本优先级、原生 node:test、拒绝直接发布/训练/下载及测试占位/错误吞没；
- Python精确 patch下限、PEP440范围转换、uv与pip导出共存、stdlib/pytest选择；
- 空测试、跳过、测试失败、审计失败及锁变化不能生成成功证明；
- 入口所有 inputs 无必填项；嵌入代码与源码一致。

Gate真值表覆盖 success/failure/cancelled/skipped/缺失输出，以及未选分支意外运行。它在 GitHub 上执行真实 Gate 脚本；这不等于对 GitHub 强制取消整个 run 的调度行为已做实测。

Actions 来源及固定 SHA 沿用 [action-pins.json](action-pins.json)。actionlint 1.7.12 下载校验固定 SHA256；PyYAML 通过 require-hashes 安装。未启用 ShellCheck，不宣称 bash -n 等于完整 shell 语义审计。

## 未测与不可代替的边界

未创建外部 caller 仓库，也未改业务项目，因此**跨仓调用、fork权限、旧多版本/多系统矩阵等价性、真实科研/应用覆盖、GPU训练、云平台、浏览器/部署验收、私有registry和整个run中途取消**未验收。自动模式的失败产物策略是不上传，不假称完成了各种第三方报告脱敏。

没有因为一个轻量 fixture 成功就声称所有项目已兼容。Python源代码检查不证明wheel正确；node命令退出成功也不能证明未知runner执行了多少测试。CPU组选取和大依赖限制见[自动识别契约](AUTOMATIC.zh-CN.md)。原有13-job或兼容矩阵需原样保留，直到项目自行证明覆盖等价后再改；本 PR 没有删减这些项目的检查。

## 首次显式模块发布（历史证据）

初始提交 [835d0365f1a05d53f1a3c49fa38d907ee3828093](https://github.com/ThaneJoss/github-ci/commit/835d0365f1a05d53f1a3c49fa38d907ee3828093) 的 [run 38344010586](https://github.com/ThaneJoss/github-ci/actions/runs/38344010586) 验证了显式 docs 嵌套调用成功路径。原五个显式 caller examples 仍固定此旧提交；它们不是自动入口的完整实测证据。行业来源、设计、安全和成本讨论继续保留在对应文档中。
