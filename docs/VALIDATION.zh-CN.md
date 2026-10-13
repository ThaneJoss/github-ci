# 验证记录与验收边界

## 已完成的 GitHub 执行

2026-10-13，经授权首次发布到公开模板仓库。模板commit [`835d0365f1a05d53f1a3c49fa38d907ee3828093`](https://github.com/ThaneJoss/github-ci/commit/835d0365f1a05d53f1a3c49fa38d907ee3828093) 的 [Template validation run 38344010586](https://github.com/ThaneJoss/github-ci/actions/runs/38344010586) 已成功，执行窗口UTC 03:55:53–03:56:09。

成功job为`Template checks`、`Reusable docs smoke / Docs / Quality`、顶层`Gate`；未选Node/Python和非法profile分支按设计skip。这次真实运行验证了同仓`validate → ci → docs`嵌套调用、checkout、docs完成证明传播及固定Gate的成功路径。

五个接入样例已固定上述真实模板SHA，仍需调用方提供真实脚本与锁。未修改其他项目，没有配置分支保护、App、凭据或部署。

## 本地与维护 CI 检查

- 10个YAML通过actionlint 1.7.12：4个可复用模块、5个caller样例、1个独立维护workflow。
- 43个shell块通过`bash -n`，4个内嵌Python块与helper/维护脚本通过语法检查。
- 156组Gate状态检查：原5个caller共80组，加维护双上游Gate的76组；包含fail/cancel/skip/缺失输出。
- 47项漏洞审计/内容helper离线测试及33项可移植性检查用例通过；公共实现未检测到仓库身份分流。
- 初始离线审查另执行60组配置边界、6组有限重试模拟；对应4个核心模块和2个helper未改变，其SHA256沿用原检查证据。
- 14份大型公开项目来源按commit/blob SHA与SHA256记录；研究文档18个固定文件/行号链接核对到已读取内容。

维护CI安装哈希固定的PyYAML Linux x86_64/Python 3.12 wheel，下载actionlint校验固定SHA256。为使本地和远端检查范围一致，actionlint显式不调用ShellCheck；`bash -n`只证明shell语法，不是完整shell语义或安全审计。Action来源见[action-pins.json](action-pins.json)，不宣称审计了其全部代码和传递下载。

## 尚未完成

跨仓调用与fork权限、Node/Python真实安装和缓存、浏览器工具、真实项目脚本、取消中途的GitHub调度、失败产物和审计CLI真实schema仍需隔离试点。成功的资料档调用不能代表这些能力已经验收，也不能证明任何应用已通过质量或线上行为验收。

核心模块不提供调用方缺失的测试、CPU锁或wheel/CLI实现。可选audit helper仅支持声明的schema及包+漏洞例外；dev/production或依赖路径限定尚未支持，未知字段会失败。资料helper不是完整Markdown/Obsidian/站点解析器，不验证anchors、wiki-links或外链可达性。静态可移植性检查只识别常见身份读取模式，不证明任意混淆代码不存在身份依赖。
