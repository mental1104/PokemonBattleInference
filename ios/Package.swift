// swift-tools-version: 6.0
// Swift 原生适配模块；C ABI 的静态库搜索路径由实际构建入口提供。
import PackageDescription

#if os(Linux)
let cppRuntime = "stdc++"
#else
let cppRuntime = "c++"
#endif

let package = Package(
    name: "PokemonCore",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [.library(name: "PokemonCore", targets: ["PokemonCore"]),
               .library(name: "PokemonAppSupport", targets: ["PokemonAppSupport"])],
    targets: [
        .systemLibrary(name: "CPokemonCore"),
        .systemLibrary(name: "CSQLite", pkgConfig: "sqlite3", providers: [.apt(["libsqlite3-dev"])]),
        .target(name: "PokemonCore", dependencies: ["CPokemonCore"],
                linkerSettings: [.linkedLibrary("pbi_abi"), .linkedLibrary("pbi_core"), .linkedLibrary(cppRuntime)]),
        // 图标按原字节复制，保留子目录及SHA；仅打包当前显式清单，不让平台PNG优化改写来源正文。
        .target(name: "PokemonAppSupport", dependencies: ["PokemonCore", "CSQLite"], resources: [
            .process("Resources/knowledge.sqlite"), .process("Resources/manifest.json"),
            .process("Resources/POKEAPI-LICENSE.txt"), .copy("Resources/Icons")
        ]),
        .testTarget(name: "PokemonCoreTests", dependencies: ["PokemonCore"]),
        .testTarget(name: "PokemonAppSupportTests", dependencies: ["PokemonAppSupport"])
    ]
)
