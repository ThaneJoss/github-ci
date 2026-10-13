# 候选模板验证状态

本包于 2026-10-13 在本地工作区验证；未发布到 GitHub，未触发任何 workflow，未运行调查项目代码或安装其依赖。

最终计数：9个YAML通过actionlint；36个shell块、80组Gate状态、60组配置边界、6组有限重试模拟通过；47项离线单元测试通过。

已执行的验证包括：全部可复用模块和调用样例的 YAML/actionlint 静态检查；shell语法检查；内嵌Python语法检查；Gate状态组合（success/failure/cancelled/skipped与输出）；配置路径/锁/超时校验；有限重试模拟；漏洞高危/低危、网络/格式错误、到期和越界例外测试；资料校验脚本的有效/失效输入。审查发现的模板状态函数位置及审计解析器边界问题已修复。

Action版本与完整SHA通过只读GitHub API解析核对，见[action-pins.json](action-pins.json)。这不是对所有被引用Action代码和传递下载的完整安全审计。静态验证使用actionlint 1.7.12；未安装ShellCheck，因此bash -n只证明shell语法，不表示完整shell语义检查。

仍需发布后的隔离试点验证：真实模板SHA可访问、workflow_call嵌套执行、runner/Action兼容、实际依赖安装与cache、browser工具和真实项目脚本、GitHub显示的唯一required check名称、fork权限、取消行为、失败产物、真实CLI审计schema、冷暖缓存墙钟及runner成本。`examples/*.yml` 的40个0是有意不可执行的引用占位，须替换为已发布的真实模板commit。

泛用模块不提供项目本身缺失的测试、CPU依赖锁或wheel/CLI实现。示例中的命令只有在调用方实现后才有实际意义；空仓不应套用。可选audit helper仅支持文档声明的schema和包+漏洞例外，不支持dev/production或依赖路径限定；未知例外字段会失败，不会被悄悄忽略。

## 公开发布准备与独立维护 CI

用户已授权仅发布公开通用部分。初始版本新增`validate.yml`：固定校验工具、47项helper测试、33项身份无关契约用例、包含caller和维护Gate在内的156组状态验证，并在同仓相对调用中实际走`validate → ci → docs`。它不包含项目名单或私有调研，且无secret、部署或权限设置操作。第一次发布前，本地10份YAML通过actionlint，43个shell块和4个内嵌Python块通过语法检查；真实GitHub结果会在首次完成后补录。此前60项配置/6项重试检查针对哈希未变的核心模块仍有效。
