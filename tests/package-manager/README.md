# 包管理器原生锁夹具

这些锁与 `tests/fixtures/pnpm` 的 picocolors 1.1.1 依赖配套：

- `pnpm-v6.yaml`：由 pnpm 8.15.9 `install --lockfile-only --ignore-scripts` 生成。
- `pnpm-12.4.2.yaml`、`pnpm-12.14.0.yaml`：将 fixture 的 `packageManager` 设为对应精确版本，再由该版本执行相同命令生成；保留包管理器与项目依赖两个 YAML 文档。

`tools/auto/smoke_package_manager.py` 只复制这些已提交的锁，不在测试期间重新生成。随后要求冻结安装成功、嵌套测试及审计通过，并验证不匹配的依赖声明被拒绝且锁不变。不要手工调整 integrity 或删除包管理器锁文档。
