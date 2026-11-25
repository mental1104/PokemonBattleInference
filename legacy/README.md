# Python 行为参考

`pokeop/`保留原Python业务、API、SQL/物化视图和静态资源，用于差分、benchmark及兼容命令。没有删除原实现或复制计算规则到Swift。

仓库根`pokeop`是指向此包的兼容软链，原`import pokeop`、`python -m pokeop...`、pytest与脚本继续使用原命名空间。CSV软链仍指向仓库固定PokeAPI子模块；common优先级仍以仓库固定引用为准。`Dockerfile.backend`保留同一真实布局和兼容导入名。

Go/C++运行入口见`docs/go-runtime.md`，Python不进入Go运行镜像。该布局先在独立工作树验证，只有完整替代验收后才纳入主迁移分支；生产切换和最终合并仍需Human授权。

2026-11-25独立工作树验证：全部原Python/自有PostgreSQL577/577通过（20.79秒），新增布局和知识包6/6通过（2.50秒），均零SKIP。新解释器移除PYTHONPATH/COMMON_ROOT后仍优先加载本仓库common；固定CSV、Swagger资源与知识包重建均通过。初轮576通过/1失败的旧Docker COPY断言已保留，随后按真实新源码路径和兼容软链严格更新，仍排除整仓复制及前端迭代噪声。Ruff及strict mypy通过。证据位于Backup/PokemonBattleInference/legacy-layout-20261125/python-r2/。

本轮实际验证了参考包及数据路径；Python兼容Dockerfile已调整COPY/软链，尚未据此声明新Python镜像完整构建成功。Go正式运行镜像仍来自主分支固定候选，不使用此准备分支。
