#!/usr/bin/env bash
# 用途：在已安装 Xcode 的 Mac 构建 arm64 iOS 设备/模拟器 Core 和 Swift 模块，无签名。
# 输入：$1 输出根目录（默认 build/apple），Boost/nlohmann-json 的 CMake package 必须可发现。
# 输出：两种 SDK 的静态库、Swift 模块、符号清单和 C ABI XCFramework；非 Mac 明确失败。
# 不登录 Apple Account、不创建证书、不连接真机，也不更改选中的 Xcode。
set -euo pipefail
readonly source_root="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
readonly output_root="${1:-$source_root/build/apple}"
[[ "$(uname -s)" == Darwin ]] || { printf 'Apple SDK builds require macOS.\n' >&2; exit 2; }
mkdir -p "$output_root/headers"
# iOS sysroot 下不自动复用 macOS 的包搜索结果；这两个依赖仅含平台无关头文件。
# 允许非 Homebrew 安装显式指定路径；发现不到时由 CMake 报错，不回退到不同版本源码。
boost_include="${PBI_BOOST_INCLUDE_DIR:-}"
json_config="${PBI_JSON_CMAKE_DIR:-}"
if command -v brew > /dev/null; then
  if [[ -z "$boost_include" ]]; then boost_include="$(brew --prefix boost)/include"; fi
  if [[ -z "$json_config" ]]; then json_config="$(brew --prefix nlohmann-json)/share/cmake/nlohmann_json"; fi
fi
package_options=()
if [[ -n "$boost_include" ]]; then
  [[ -f "$boost_include/boost/version.hpp" ]] || { printf 'Boost headers are unavailable.\n' >&2; exit 2; }
  package_options+=("-DBoost_INCLUDE_DIR:PATH=$boost_include")
fi
if [[ -n "$json_config" ]]; then
  [[ -f "$json_config/nlohmann_jsonConfig.cmake" ]] || { printf 'nlohmann_json CMake package is unavailable.\n' >&2; exit 2; }
  package_options+=("-Dnlohmann_json_DIR:PATH=$json_config")
fi
cp "$source_root/contracts/c/pbi_core.h" "$output_root/headers/pbi_core.h"
cat > "$output_root/headers/module.modulemap" <<'MODULE'
module CPokemonCore {
  header "pbi_core.h"
  export *
}
MODULE
xcodebuild -version > "$output_root/xcode-version.txt"
xcrun swiftc --version > "$output_root/swift-version.txt"
for sdk in iphoneos iphonesimulator; do
  build_path="$output_root/$sdk"
  sdk_path="$(xcrun --sdk "$sdk" --show-sdk-path)"
  target=arm64-apple-ios16.0
  if [[ "$sdk" == iphonesimulator ]]; then target=arm64-apple-ios16.0-simulator; fi
  cmake -S "$source_root/core" -B "$build_path" -DBUILD_TESTING=OFF \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_SYSROOT="$sdk_path" \
    -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=16.0 \
    -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY "${package_options[@]}"
  cmake --build "$build_path" --target pbi_abi --parallel 2
  xcrun libtool -static -o "$build_path/libPBIEngine.a" "$build_path/libpbi_abi.a" "$build_path/libpbi_core.a"
  xcrun nm -gU "$build_path/libPBIEngine.a" > "$build_path/symbols.txt"
  # 核对交付 archive 确实导出 C ABI 入口，不把仅生成头文件当作构建成功。
  awk '$NF == "_pbi_v1_compute" { found=1 } END { exit !found }' "$build_path/symbols.txt"
  xcrun swiftc -sdk "$sdk_path" -target "$target" -parse-as-library \
    -I "$source_root/ios/Sources/CPokemonCore" \
    -emit-library -static -emit-module -enable-library-evolution -module-name PokemonCore \
    -emit-module-path "$build_path/PokemonCore.swiftmodule" \
    -o "$build_path/libPokemonCore.a" "$source_root/ios/Sources/PokemonCore/Engine.swift"
done
# xcodebuild 会核对两个 archive 的平台元数据；拒绝将重复/错误平台伪装为设备和模拟器。
xcodebuild -create-xcframework \
  -library "$output_root/iphoneos/libPBIEngine.a" -headers "$output_root/headers" \
  -library "$output_root/iphonesimulator/libPBIEngine.a" -headers "$output_root/headers" \
  -output "$output_root/PBIEngine.xcframework"
