#!/bin/sh
# 用途：仅通过 DSM 官方本地 API 建立 pokemon.mental1104.xyz 的 HTTPS 反代并绑定既有通配证书。
# 输入：唯一动作 snapshot/create/assign/sync/test/reload/final；不接受域名、目标地址、UUID 或命令参数。
# 输出：固定动作结果，详细 JSON 写入预先由调用用户创建的私有 Backup 文件；失败返回非零。
# 依赖：DSM synowebapi/synow3tool、jq、openssl；在固定 chroot maintenance 入口以宿主 root 执行。
# 副作用：create/assign/sync/reload 仅处理本次 Pokemon 规则；不编辑 Pomerium，不更换证书或登录策略。
set -eu
umask 077
pokemon_records=/volume1/homes/mental1104/Backup/PokemonBattleInference/nas-deployment-20261125/https
pokemon_rules=/usr/syno/etc/www/ReverseProxy.json
readonly pokemon_records pokemon_rules
[ "$(id -u)" = 0 ] && [ "$(hostname)" = Condemned-Tower ] && [ "$#" = 1 ] || exit 2
[ -d "$pokemon_records" ] && [ ! -L "$pokemon_records" ] || exit 2

# $1 是固定的 CRT API 输出文件名；读取全部证书和绑定但不读取私钥，不修改 DSM。
# 目标文件必须已由维护者创建，保留其所有者及 0600 权限；API 失败返回非零。
certificate_list() {
  [ -f "$pokemon_records/$1" ] && [ ! -L "$pokemon_records/$1" ] || exit 2
  /usr/syno/bin/synowebapi --exec api=SYNO.Core.Certificate.CRT method=list version=1 > "$pokemon_records/$1"
  /bin/jq -e '.success == true and (.data.certificates | type == "array")' "$pokemon_records/$1" >/dev/null
}

# 从本次记录加载 UUID 并核对实际前后端；只允许本域名的精确 127.0.0.1:41110 规则。
# 不读取外部 UUID 参数，成功输出 UUID，失败拒绝后续证书写入或同步。
proxy_id() {
  pokemon_id="$(cat "$pokemon_records/proxy-id.txt")"
  /bin/jq -e --arg id "$pokemon_id" '.[$id] | .frontend.fqdn == "pokemon.mental1104.xyz" and .frontend.port == 443 and .frontend.protocol == 1 and .backend.fqdn == "127.0.0.1" and .backend.port == 41110 and .backend.protocol == 0' "$pokemon_rules" >/dev/null
  case "$pokemon_id" in ''|*[!a-f0-9-]*) exit 2;; esac
  [ "${#pokemon_id}" = 36 ] || exit 2
  printf '%s\n' "$pokemon_id"
}

case "$1" in
  snapshot)
    # 初次快照必须完整保存全部规则及证书服务绑定，之后不覆盖这个基线。
    if [ -s "$pokemon_records/proxies.before.json" ] && [ -s "$pokemon_records/certificates.before.json" ]; then
      # 检查中断后的重试保留原基线；只有实际规则仍与基线完全相同时才允许继续验证。
      cmp "$pokemon_rules" "$pokemon_records/proxies.before.json"
    else
      cat "$pokemon_rules" > "$pokemon_records/proxies.before.json"
      cat /usr/syno/etc/certificate/_archive/INFO > "$pokemon_records/certificate-archive-info.before.json"
      certificate_list certificates.before.json
    fi
    # DSM 文件同时包含数字 version 元数据；仅规则对象具有 frontend。
    /bin/jq -e 'all(.[] | select(type == "object"); .frontend.fqdn != "pokemon.mental1104.xyz")' "$pokemon_records/proxies.before.json" >/dev/null
    /bin/jq -e '.data.certificates[] | select(.id == "511AVs") | .is_broken == false and (.subject.sub_alt_name | index("*.mental1104.xyz") != null)' "$pokemon_records/certificates.before.json" >/dev/null
    /bin/openssl x509 -in /usr/syno/etc/certificate/_archive/511AVs/cert.pem -checkend 0 -noout
    /bin/openssl x509 -in /usr/syno/etc/certificate/_archive/511AVs/cert.pem -noout -subject -issuer -dates > "$pokemon_records/wildcard-public-cert.txt"
    printf 'Snapshot complete; existing wildcard certificate verified.\n'
    ;;
  create)
    /bin/jq -e 'all(.[] | select(type == "object"); .frontend.fqdn != "pokemon.mental1104.xyz")' "$pokemon_rules" >/dev/null
    /bin/jq -e 'type == "object" and length > 0' "$pokemon_records/proxies.before.json" >/dev/null
    # 请求体固定生成，不能把任意 JSON 写入反代 API；与应用代理一致使用120秒读取超时。
    cat > "$pokemon_records/entry.json" <<'JSON'
{"backend":{"fqdn":"127.0.0.1","port":41110,"protocol":0},"customize_headers":[{"name":"Upgrade","value":"$http_upgrade"},{"name":"Connection","value":"$connection_upgrade"}],"description":"Pokemon","frontend":{"acl":null,"fqdn":"pokemon.mental1104.xyz","https":{"hsts":false},"port":443,"protocol":1},"proxy_connect_timeout":10,"proxy_http_version":1,"proxy_intercept_errors":false,"proxy_read_timeout":120,"proxy_send_timeout":120}
JSON
    /usr/syno/bin/synowebapi --exec api=SYNO.Core.AppPortal.ReverseProxy method=create version=1 "entry=$(cat "$pokemon_records/entry.json")" > "$pokemon_records/proxy-create.json"
    /bin/jq -e '.success == true' "$pokemon_records/proxy-create.json" >/dev/null
    cat "$pokemon_rules" > "$pokemon_records/proxies.after-create.json"
    /bin/jq -r --slurpfile before "$pokemon_records/proxies.before.json" '((keys - ($before[0] | keys)) | if length == 1 then .[0] else error("expected exactly one new rule") end)' "$pokemon_records/proxies.after-create.json" > "$pokemon_records/proxy-id.txt"
    proxy_id
    ;;
  assign)
    pokemon_id="$(proxy_id)"
    certificate_list certificates.after-create.json
    # 保留 DSM 返回的服务对象，只变更该 UUID 的证书 ID，其他服务不进入 set 请求。
    /bin/jq --arg id "$pokemon_id" '[.data.certificates[] | .id as $old | .services[]? | select(.subscriber == "ReverseProxy" and .service == $id) | {id:"511AVs",old_id:$old,service:.}] | if length == 1 then . else error("expected exactly one Pokemon certificate service") end' "$pokemon_records/certificates.after-create.json" > "$pokemon_records/certificate-settings.json"
    /usr/syno/bin/synowebapi --exec api=SYNO.Core.Certificate.Service method=set version=1 "settings=$(cat "$pokemon_records/certificate-settings.json")" > "$pokemon_records/certificate-assign.json"
    /bin/jq -e '.success == true' "$pokemon_records/certificate-assign.json" >/dev/null
    printf 'Pokemon certificate binding assigned.\n'
    ;;
  sync)
    pokemon_id="$(proxy_id)"
    exec /usr/syno/bin/synow3tool "--sync-cert-repository=/usr/syno/etc/certificate/ReverseProxy/$pokemon_id/info"
    ;;
  test) exec /usr/bin/nginx -t ;;
  reload) exec /usr/syno/bin/synosystemctl reload nginx ;;
  final)
    pokemon_id="$(proxy_id)"
    cat "$pokemon_rules" > "$pokemon_records/proxies.final.json"
    cat /usr/syno/etc/certificate/_archive/INFO > "$pokemon_records/certificate-archive-info.final.json"
    certificate_list certificates.final.json
    # 只允许新增本应用规则；其他反代规则的全部字段必须与快照逐字等价。
    /bin/jq -S 'del(.version)' "$pokemon_records/proxies.before.json" > "$pokemon_records/other-proxies.before.json"
    /bin/jq -S --arg id "$pokemon_id" 'del(.version, .[$id])' "$pokemon_records/proxies.final.json" > "$pokemon_records/other-proxies.final.json"
    cmp "$pokemon_records/other-proxies.before.json" "$pokemon_records/other-proxies.final.json"
    /bin/jq -e --arg id "$pokemon_id" '.data.certificates[] | select(.id == "511AVs") | any(.services[]?; .subscriber == "ReverseProxy" and .service == $id)' "$pokemon_records/certificates.final.json" >/dev/null
    printf 'Pokemon proxy and wildcard certificate verified; other proxy rules unchanged.\n'
    ;;
  *) printf 'Unsupported Pokemon HTTPS maintenance operation.\n' >&2; exit 2;;
esac
