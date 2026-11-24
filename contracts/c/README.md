# C ABI v1 与跨语言计算合同

权威 C 声明为 `pbi_core.h`，JSON 的固定成功向量为 `tests/vectors/abi-calculations.v1.{request,response}.json`。Go/Swift 读取同一头文件并链接同一 Core 源码产生的静态库，不维护第二份计算规则。

## 生命周期与错误

`pbi_v1_compute` 同步借用 request 字节；长度必须准确，返回前不得修改。调用者零初始化 `pbi_buffer_v1`，返回 JSON 由 Core 独占分配，必须用 `pbi_v1_buffer_release` 归还；不能用 Go/Swift 的 allocator 释放。release 清零且可重复调用。非空 output 不会被覆盖，避免丢失尚未释放的结果。

JSON 不是 NUL 终止字符串，必须读取完整 size。Go 使用 `C.GoBytes`、Swift 使用 `Data(bytes:count:)` 复制，再释放 C 缓冲区。错误正文同样遵守这个生命周期。内存耗尽或 output 参数错误时允许没有正文，仍返回状态码。

| C 状态码 | JSON error.code | 首批 Go HTTP 映射 |
| --- | --- | --- |
| 0 / OK | 无 error，含 results | 200 |
| 1 / INVALID_INPUT | invalid_input | 400 |
| 2 / UNSUPPORTED | unsupported | 422 |
| 3 / RESOURCE_LIMIT | resource_limit | 413 |
| 4 / CANCELLED | cancelled | 408；Go context deadline 为 504 |
| 5 / INTERNAL_ERROR | internal_error | 500 |

C++ 的协议、参数、溢出、分配及未知异常全部在 ABI 内捕获；不通过全局/线程 last-error 传错。异常消息是固定 ASCII 或 Core 的稳定 ASCII 文本，不回显请求。SIGSEGV/abort 等进程级故障不能由 C++ catch 或 CGO 隔离；P3 的复杂推演必须由独立 Worker 进程承担，当前同步 Go 首批计算服务不是这一隔离方案的替代。

## 批次与版本

请求只有 `schema_version: 1` 和非空 `operations`，操作按数组顺序返回。任一成员错误、超限或取消，整批只返回 error，不提供部分 results。没有数据库/用户数据写入，也没有任务 ID、进度或持久化副作用。

成功/原生错误正文包括 `schema_version`、`engine_version`、`rules_version`。当前引擎为 `0.1.0`，首批规则标识为 `modern-calculations.v1`；不表示完整宝可梦规则已迁移。发布后的语义变更必须更新引擎/规则版本，不能让同一版本悄悄产生不同结果。

| kind | 完整输入字段（均不含 kind 自身） | 结果 |
| --- | --- | --- |
| hp | base、iv、ev、level，均 int32 | value：int64 |
| stat | 上述字段及 nature_tenths：9/10/11 | value：int64 |
| stage | value：int64，stage：int32 且 -6…6 | value：int64，至少 1；原 value 必须正数 |
| ko | defender_hp：正 int32，rolls：非空 int32 数组 | ohko、two_hit：精确分子/分母字符串；guaranteed_ohko、guaranteed_two_hit：布尔值 |

未知字段、缺失字段、bool/float 冒充整数、越界整数均拒绝。未知 kind、schema version 或性格倍率明确返回 UNSUPPORTED。KO 的重复槽位保留等概率权重，不处理回血/残余伤害；完整领域边界和极端整数行为差异见 `core/README.md`。

概率分子、分母使用任意精度整数与精确有理数，不经过 double；零规范为 `0/1`。HTTP 小数展示或 Swift UI 展示转换不能反过来作为计算输入的精确概率来源。

v1 资源上限声明在头文件：8 MiB 请求、4,096 操作、单操作 65,536 伤害槽位、批次合计 1,048,576 槽位；解析深度最多 16。超限失败，不截断后重新归一化。这些是当前 ABI 批次预算，不能混同后续状态图的节点/边/回合截断合同。

## 取消与并发

`pbi_v1_cancel_token_create` 创建单向原子令牌，cancel 可与 compute 并发。令牌允许多个计算只读借用，取消影响所有借用者；不能重置。所有调用返回且所有并发 cancel 结束后，创建者才可 destroy。空令牌表示本次不提供取消。

Core 在解析前、操作解码/执行之间及结果提交前检查取消。JSON 解析和单个 bounded KO 的排序不会被强制中断；取消属于协作式，不能承诺瞬时抢占。取消与最后提交检查竞争时，已完成的调用允许返回 OK。独立输入/输出可并发调用，无共享可变计算状态。

Go 在每次调用内拥有令牌、C 输入副本和结果。监视 context 的 goroutine 完全退出后才 destroy，避免 use-after-free。Swift 用强引用和 withExtendedLifetime 保持令牌，calculateAsync 在 detached task 执行并传播 Task 取消，计算不占 MainActor。

## 实际验证与入口

- Linux C/C++：13 项 CTest，含真正的 C 编译器调用、完整共享向量、非法输入/预算、循环释放、32 并发及实际运行中取消。ASan/UBSan/leak 检查同样 13/13 通过。
- Go：3 项桥接测试加 1 项回环 HTTP 测试，`-race` 与 `go vet` 通过。外部静态库不参与 Go 缓存跟踪，所以测试/交付构建使用 `-a`。
- Swift 6 Linux：4 项 XCTest，通过实际 Core 静态库；完整结果/版本、错误/释放、32 并发、Task 运行中取消均已执行。Swift scratch 以两个原生 archive 的 SHA-256 区分，避免增量缓存链接旧库。
- 独立 NAS curl 到实际 Go 服务容器：200 完整共享向量匹配，未知操作 422 且无部分结果；临时服务和随机回环端口已清理。

本地统一入口：`make test` 或 `make test-native`。仅缺少未显式配置的 Go/Swift 工具时，pytest 会说明能力缺失并 SKIP；显式工具/库配置错误必须 FAIL。NAS 的 `validate-nas.sh bindings` 委托两个声明的 maintenance 工具环境，弥补 Python 镜像未含 Swift 的能力；不是把其跳过结果算成通过。

macOS/iOS 已由用户授权的 [GitHub Ready-PR CI 45343368822](https://github.com/mental1104/PokemonBattleInference/actions/runs/45343368822) 实际验证：macOS CTest 13/13、差分和双语言委托 6/6 无跳过；arm64 iPhoneOS/Simulator archive、Swift 模块和 C ABI XCFramework 均构建成功。下载的 ZIP 校验值、两个平台与共享头已独立核验，证据见 `docs/migration-progress.md`。Apple SDK 编译不需要登录或签名，不安装 App、不执行签名、不代表模拟器运行或 iPhone/iPad 真机验收。
