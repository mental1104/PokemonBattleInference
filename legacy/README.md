# Python 行为参考

`pokeop/`保留原Python业务、API、SQL/物化视图和静态资源，用于差分、benchmark及兼容命令。没有删除原实现或复制计算规则到Swift。

仓库根`pokeop`是指向此包的兼容软链，原`import pokeop`、`python -m pokeop...`、pytest与脚本继续使用原命名空间。CSV软链仍指向仓库固定PokeAPI子模块；common优先级仍以仓库固定引用为准。`Dockerfile.backend`保留同一真实布局和兼容导入名。

Go/C++运行入口见`docs/go-runtime.md`，Python不进入Go运行镜像。该布局先在独立工作树验证，17a5fda完整替代及NAS/HDD验收通过后，以2036989纳入当前迁移分支。NAS部署已获授权并完成；最终合并和双真机验收仍待Human。

2026-11-25独立工作树验证：全部原Python/自有PostgreSQL577/577通过（20.79秒），新增布局和知识包6/6通过（2.50秒），均零SKIP。新解释器移除PYTHONPATH/COMMON_ROOT后仍优先加载本仓库common；固定CSV、Swagger资源与知识包重建均通过。初轮576通过/1失败的旧Docker COPY断言已保留，随后按真实新源码路径和兼容软链严格更新，仍排除整仓复制及前端迭代噪声。Ruff及strict mypy通过。证据位于Backup/PokemonBattleInference/legacy-layout-20261125/python-r2/。

上述独立工作树检查只证明参考包及数据路径，当时未构建新Python镜像。当前集成后的完整回归及兼容Dockerfile实际构建另行记录，不能继承早期检查结果；NAS继续使用已验收的p6-sv-filesystem-r1 Go镜像，不部署Python参考镜像。

2036989集成后复验：原Python/真实自有PG577/577，布局/知识包6/6，Ruff/strict mypy均通过；make coverage的领域/应用层461项通过，统计实体路径覆盖率84%。复用固定.11产物的迁移差分126 PASS/247外部SKIP。实际兼容镜像pokemon-python-reference:legacy-2036989构建成功，ID为sha256:618f72e3c851adea8f29ad507b3ad73f0d8e1ce3bf90dee395ae09a129f34f41；用deploy/compose.legacy-image-validation.yaml仅挂载测试文件、不挂源码，在镜像内3/3通过。证据在legacy-layout-20261125/integrated-r2/及python-image-build.log。

Python参考运行环境需同时安装requirements.txt和requirements-legacy-runtime.txt。后者提取原backend/维护镜像已有的12项common顶层运行依赖，CI和镜像共用，不增加Go/Swift运行依赖。7a09554的Hosted CI只有基础清单，真实新进程导入common时因缺genanki失败；全依赖NAS测试环境此前能够通过。纯Python基础镜像新venv复现相同错误后，只补运行清单即可真实导入固定common；定向10项和完整595 PASS/361环境SKIP通过，未跳过或替换真实导入断言。证据在legacy-ci-dependencies-20261125/，缺失能力的SKIP不计为通过。
