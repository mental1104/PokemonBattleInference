#!/usr/bin/env bash
# 在具备 Xcode/iOS Runtime 的 Mac 上生成真实工程并运行 iPhone、iPad UI 验收。
# 参数1：仓库根目录（默认由脚本位置推导）。依赖 xcodegen、jq、xcrun、xcodebuild。
# 输出：build/reports/app/ 中的日志、设备清单、xcresult 与截图；失败保留证据并返回非零。
# 副作用：只生成工程/构建产物和启动选定模拟器，不操作证书、签名或物理设备。
set -euo pipefail
repo="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
reports="$repo/build/reports/app"
mkdir -p "$reports"
# 参数为当前实际阶段；时间写入独立报告，区分构建、启动、测试和导出耗时。
record_phase() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$reports/timing.log"; }
record_phase generate-project
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
record_phase build-device-app
xcodebuild build -project "$repo/ios/PokemonBattleInference.xcodeproj" -scheme PokemonBattleInference \
    -destination 'generic/platform=iOS' -derivedDataPath "$repo/build/app-device" \
    CODE_SIGNING_ALLOWED=NO 2>&1 | tee "$reports/device-build.log"
overall_status=0
for family in iPhone iPad; do
    record_phase "$family select-and-boot"
    device="$(jq -r --arg family "$family" '[.[] | select(.name | startswith($family))][0].udid // empty' "$reports/ios-devices.json")"
    if [[ -z "$device" ]]; then echo "Missing available $family iOS simulator" >&2; exit 1; fi
    state="$(jq -r --arg device "$device" '.[] | select(.udid == $device) | .state' "$reports/ios-devices.json")"
    if [[ "$state" != Booted ]]; then xcrun simctl boot "$device"; booted_by_script+=("$device"); fi
    xcrun simctl bootstatus "$device" -b
    vm_stat > "$reports/$family-memory-before-test.txt"
    sysctl vm.swapusage >> "$reports/$family-memory-before-test.txt"
    echo "$family $device" | tee -a "$reports/selected-devices.txt"
    # 管道保留 xcodebuild 失败状态，失败后的截图仍在退出前获取。
    status=0
    record_phase "$family xcodebuild-test-start"
    xcodebuild test -project "$repo/ios/PokemonBattleInference.xcodeproj" -scheme PokemonBattleInference \
        -destination "platform=iOS Simulator,id=$device" -derivedDataPath "$repo/build/app-simulator" \
        -parallel-testing-enabled NO -maximum-concurrent-test-simulator-destinations 1 \
        -resultBundlePath "$reports/$family.xcresult" CODE_SIGNING_ALLOWED=NO \
        2>&1 | tee "$reports/$family-test.log" || status=$?
    record_phase "$family xcodebuild-test-finish status=$status"
    # 导出测试过程中的实际附件；测试退出后 App 已关闭，单张最终截图不能代替失败现场。
    xcrun xcresulttool export attachments --path "$reports/$family.xcresult" \
        --output-path "$reports/$family-attachments" > "$reports/$family-export.log" 2>&1 || true
    xcrun simctl io "$device" screenshot "$reports/$family-final.png" || true
    record_phase "$family export-finish"
    printf '%s %s\n' "$family" "$status" >> "$reports/test-exit-codes.txt"
    # 一个机型的断言失败仍收集另一机型的独立证据；最终保留失败退出码，不将失败算作通过。
    if [[ "$status" != 0 ]]; then overall_status=1; fi
    # 只关闭本轮自启的模拟器，释放资源后再启动另一机型；用户预先运行的设备不受影响。
    if [[ "$state" != Booted ]]; then
        if xcrun simctl shutdown "$device"; then booted_by_script=(); fi
        record_phase "$family shutdown-owned-simulator"
    fi
done
exit "$overall_status"
