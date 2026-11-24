#!/usr/bin/env bash
# 用途：macOS/Linux 在相同 SwiftPM 入口测试当前 Core 静态库，不处理签名或设备授权。
# 输入：$1 为已构建的 Core 目录（默认 build/core）；PBI_SWIFT 可指定 Swift 工具。
# 输出：原生 Swift 测试输出/退出码；缓存和可执行临时文件仅写构建目录的父目录。
# 外部静态库不受 SwiftPM 源码跟踪，因此以两个 archive 的 SHA-256 命名 scratch，避免陈旧链接。
set -euo pipefail
readonly source_root="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
readonly core_directory="${1:-$source_root/build/core}"
readonly build_base="$(cd "$core_directory/.." && pwd -P)"
abi_hash="$(cmake -E sha256sum "$core_directory/libpbi_abi.a")"
abi_hash="${abi_hash%% *}"
core_hash="$(cmake -E sha256sum "$core_directory/libpbi_core.a")"
core_hash="${core_hash%% *}"
mkdir -p "$build_base/swift-tmp"
export TMPDIR="$build_base/swift-tmp"
export CLANG_MODULE_CACHE_PATH="$build_base/swift-modules"
export SWIFTPM_MODULECACHE_OVERRIDE="$build_base/swift-modules"
export PBI_CONTRACT_FIXTURES="$source_root/tests/vectors"
exec "${PBI_SWIFT:-swift}" test --package-path "$source_root/ios" \
  --scratch-path "$build_base/swift-$abi_hash-$core_hash" \
  --cache-path "$build_base/swift-cache" --config-path "$build_base/swift-config" \
  --security-path "$build_base/swift-security" -Xlinker "-L$core_directory"
