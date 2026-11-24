#!/usr/bin/env bash
# 在具备 Xcode/iOS Runtime 的 Mac 上生成真实工程并运行 iPhone、iPad UI 验收。
# 参数1：仓库根目录（默认由脚本位置推导）。依赖 xcodegen、jq、xcrun、xcodebuild。
# 输出：build/reports/app/ 中的日志、设备清单、xcresult 与截图；失败保留证据并返回非零。
# 副作用：只生成工程/构建产物和启动选定模拟器，不操作证书、签名或物理设备。
set -euo pipefail
repo="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
reports="$repo/build/reports/app"
mkdir -p "$reports"
xcodegen generate --spec "$repo/ios/project.yml"
xcrun simctl list devices available --json > "$reports/available-devices.json"
# 仅选择实际已安装的 iOS runtime；UUID 固定当前测试目标，不猜测 runner 的设备名称。
jq '[.devices | to_entries[] | select(.key | contains("iOS")) | .value[] | select(.isAvailable)]' "$reports/available-devices.json" > "$reports/ios-devices.json"
booted_by_script=()
# 退出时只关闭本脚本从关机状态启动的设备；已有运行中的模拟器保持原状。
cleanup() {
    # macOS 自带 Bash 3 的 nounset 不接受空数组展开，清理阶段允许空设备集合。
    set +u
    for device in "${booted_by_script[@]}"; do xcrun simctl shutdown "$device" || true; done
}
trap cleanup EXIT
xcodebuild build -project "$repo/ios/PokemonBattleInference.xcodeproj" -scheme PokemonBattleInference \
    -destination 'generic/platform=iOS' -derivedDataPath "$repo/build/app-device" \
    CODE_SIGNING_ALLOWED=NO 2>&1 | tee "$reports/device-build.log"
for family in iPhone iPad; do
    device="$(jq -r --arg family "$family" '[.[] | select(.name | startswith($family))][0].udid // empty' "$reports/ios-devices.json")"
    if [[ -z "$device" ]]; then echo "Missing available $family iOS simulator" >&2; exit 1; fi
    state="$(jq -r --arg device "$device" '.[] | select(.udid == $device) | .state' "$reports/ios-devices.json")"
    if [[ "$state" != Booted ]]; then xcrun simctl boot "$device"; booted_by_script+=("$device"); fi
    xcrun simctl bootstatus "$device" -b
    echo "$family $device" | tee -a "$reports/selected-devices.txt"
    # 管道保留 xcodebuild 失败状态，失败后的截图仍在退出前获取。
    status=0
    xcodebuild test -project "$repo/ios/PokemonBattleInference.xcodeproj" -scheme PokemonBattleInference \
        -destination "platform=iOS Simulator,id=$device" -derivedDataPath "$repo/build/app-simulator" \
        -parallel-testing-enabled NO -maximum-concurrent-test-simulator-destinations 1 \
        -resultBundlePath "$reports/$family.xcresult" CODE_SIGNING_ALLOWED=NO \
        2>&1 | tee "$reports/$family-test.log" || status=$?
    xcrun simctl io "$device" screenshot "$reports/$family-final.png" || true
    if [[ "$status" != 0 ]]; then exit "$status"; fi
done
