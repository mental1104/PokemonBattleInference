#!/usr/bin/env bash
# 在具备 Xcode/iOS Runtime 的 Mac 上生成真实工程并运行 iPhone、iPad UI 验收。
# 参数1：仓库根目录（默认由脚本位置推导）。依赖 XcodeGen/jq/Xcode/Go/完整PostgreSQL工具与固定CSV。
# 输出：build/reports/app/ 中的日志、设备清单、xcresult 与截图；失败保留证据并返回非零。
# 副作用：只在build自有目录初始化独立PG/Go服务并启动选定模拟器，不操作生产DB、证书或物理设备。
set -euo pipefail
repo="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
reports="$repo/build/reports/app"
mkdir -p "$reports"
# 参数为当前实际阶段；时间写入独立报告，区分构建、启动、测试和导出耗时。
record_phase() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$reports/timing.log"; }
booted_by_script=()
services="$(mktemp -d "$repo/build/app-online.XXXXXX")"
server_pid=""
worker_pid=""
pg_bin=""
pg_started=false
# 参数为本脚本$!记录的PID；先正常退出，超过五秒才终止该精确自有进程，绝不按名称批量操作。
stop_owned_process() {
    local owned_pid="$1"
    [[ -n "$owned_pid" ]] || return 0
    kill -TERM "$owned_pid" 2>/dev/null || true
    for _ in {1..50}; do if ! kill -0 "$owned_pid" 2>/dev/null; then break; fi; sleep .1; done
    if kill -0 "$owned_pid" 2>/dev/null; then kill -KILL "$owned_pid" 2>/dev/null || true; fi
    wait "$owned_pid" 2>/dev/null || true
}
# 退出时只关闭本脚本从关机状态启动的设备；已有运行中的模拟器保持原状。
cleanup() {
    # macOS 自带 Bash 3 的 nounset 不接受空数组展开，清理阶段允许空设备集合。
    set +u
    for device in "${booted_by_script[@]}"; do xcrun simctl shutdown "$device" || true; done
    stop_owned_process "$worker_pid"
    stop_owned_process "$server_pid"
    if [[ "$pg_started" == true ]]; then "$pg_bin/pg_ctl" -D "$services/postgres" stop -m fast -w >> "$reports/postgres-cleanup.log" 2>&1 || true; fi
}
trap cleanup EXIT
record_phase build-real-go-services
mkdir -p "$services/bin"
(
    cd "$repo/server"
    # 外部静态archive不受Go源码缓存追踪；本次明确重链当前Mac Core，四个正式二进制共用一轮build。
    CGO_LDFLAGS="-L$repo/build/core" go build -a -o "$services/bin/" ./cmd/pbi-server ./cmd/pbi-core-worker ./cmd/pbi-worker ./cmd/pbi-db-init
) > "$reports/go-services-build.log" 2>&1
if command -v pg_config >/dev/null; then pg_bin="$(pg_config --bindir)"; fi
if [[ -z "$pg_bin" || ! -x "$pg_bin/initdb" || ! -x "$pg_bin/pg_ctl" ]]; then pg_bin="$(brew --prefix postgresql@16)/bin"; fi
[[ -x "$pg_bin/initdb" && -x "$pg_bin/pg_ctl" ]]
"$pg_bin/pg_config" --version > "$reports/postgres-version.txt"
# 只探测未占用回环端口，不查询任何现有PG；子进程存活和pg_ctl -w再次验证实际启动成功。
pg_port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
record_phase initialize-independent-postgres
"$pg_bin/initdb" -D "$services/postgres" --username=pbi_ui --encoding=UTF8 --no-locale --auth=trust > "$reports/postgres-init.log" 2>&1
pg_started=true
"$pg_bin/pg_ctl" -D "$services/postgres" -l "$reports/postgres.log" -o "-h 127.0.0.1 -p $pg_port -c unix_socket_directories= -c shared_buffers=64MB -c max_connections=40" -w start >> "$reports/postgres-init.log" 2>&1
"$pg_bin/createdb" -h 127.0.0.1 -p "$pg_port" -U pbi_ui pbi_ui
api_port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
database="postgres://pbi_ui@127.0.0.1:$pg_port/pbi_ui?sslmode=disable"
PBI_POSTGRES_DSN="$database" "$services/bin/pbi-db-init" --csv-root "$repo/submodules/pokeapi/data/v2/csv" > "$reports/knowledge-import.json" 2> "$reports/knowledge-import.log"
endpoint="http://127.0.0.1:$api_port"
PBI_LISTEN="127.0.0.1:$api_port" PBI_POSTGRES_DSN="$database" PBI_CORE_WORKER_PATH="$services/bin/pbi-core-worker" \
    "$services/bin/pbi-server" > "$reports/go-server.log" 2>&1 &
server_pid=$!
ready=false
for _ in {1..100}; do
    kill -0 "$server_pid"
    if curl -fsS --max-time 1 "$endpoint/healthz" > "$reports/go-health.json" 2>/dev/null; then ready=true; break; fi
    sleep .1
done
[[ "$ready" == true ]]
PBI_POSTGRES_DSN="$database" "$services/bin/pbi-worker" --revision battle-inference.summary-exploration.v2 \
    --native-executable "$services/bin/pbi-core-worker" > "$reports/go-worker.log" 2>&1 &
worker_pid=$!
sync_user="apple-ui-$(date +%s)-$$"
curl -fsS --max-time 35 -H 'Content-Type: application/json' --data-binary "@$repo/tests/vectors/abi-calculations.v1.request.json" \
    "$endpoint/v1/core/calculate" > "$reports/go-core-probe.json"
engine_version="$(jq -er '.engine_version' "$reports/go-core-probe.json")"
rules_version="$(jq -er '.rules_version' "$reports/go-core-probe.json")"
knowledge_version="$(jq -er '.data_version' "$repo/ios/Sources/PokemonAppSupport/Resources/manifest.json")"
jq -n --arg server "$endpoint" --arg user "$sync_user" --arg engine "$engine_version" --arg rules "$rules_version" --arg knowledge "$knowledge_version" \
    '{serverURL:$server,syncUser:$user,engineVersion:$engine,rulesVersion:$rules,knowledgeVersion:$knowledge}' > "$reports/online-services.json"
record_phase real-go-postgres-ready
# 之前缺环境的正式Swift在线/双SQLite同步现在连接同一个独立Go+PG实例；不是UI替身或结果注入。
PBI_ONLINE_TEST_URL="$endpoint" PBI_SYNC_TEST_URL="$endpoint" PBI_CONFIGURATION_JOB_TEST_URL="$endpoint" \
    PBI_CONFIGURATION_JOB_REPORT_DIRECTORY="$reports/jobs" PBI_ONLINE_REPORT_DIRECTORY="$reports/online-contracts" \
    bash "$repo/tools/migration/test-swift.sh" "$repo/build/core" > "$reports/swift-real-online-sync.log" 2>&1
record_phase generate-project
xcodegen generate --spec "$repo/ios/project.yml"
xcrun simctl list devices available --json > "$reports/available-devices.json"
# 仅选择实际已安装的 iOS runtime；UUID 固定当前测试目标，不猜测 runner 的设备名称。
jq '[.devices | to_entries[] | select(.key | contains("iOS")) | .value[] | select(.isAvailable)]' "$reports/available-devices.json" > "$reports/ios-devices.json"
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
