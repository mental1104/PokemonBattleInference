#!/usr/bin/env bash
# 用途：仅把仓库中明确选取的朱紫小图标包发布到HDD，不再复制全量上游图片。
# 输入：参数1为data/assets/scarlet-violet包目录，参数2为拥有该包的项目Git提交，参数3为HDD快照父目录。
# 输出：成功输出正式快照路径；相同版本核验后复用，失败不覆盖历史目录。
# 依赖：Git、jq、sha256sum、GNU cp/find；副作用仅写受控小图标快照与核验文件。
# manifest.source_commit是PokeAPI上游身份；HDD目录/PG批次使用项目Git版本，清单更新不会覆盖旧快照。
set -euo pipefail
umask 077
[[ $# == 3 ]] || exit 2
readonly source_root="$1" expected_commit="$2" snapshot_root="$3"
[[ "$source_root" == /* && "$snapshot_root" == /* && "$expected_commit" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ "$(git -C "$source_root" rev-parse HEAD)" == "$expected_commit" ]] || exit 2
[[ -z "$(git -C "$source_root" status --porcelain -- .)" ]] || { echo 'Selected icon package must be committed and clean' >&2; exit 2; }
jq -e '.game == "scarlet-violet" and .asset_count == (.assets|length) and .asset_count > 0 and .byte_size <= 33554432 and all(.assets[]; (.server_path | test("^[a-zA-Z0-9/-]+\\.png$")) and (.sha256 | test("^[0-9a-f]{64}$")))' "$source_root/manifest.json" >/dev/null
readonly expected_files="$(jq -r '.asset_count' "$source_root/manifest.json")"
readonly destination="$snapshot_root/$expected_commit"
mkdir -p "$snapshot_root"
chmod 700 "$snapshot_root"
if [[ -d "$destination" ]]; then
  cmp "$source_root/manifest.json" "$destination/manifest.json"
  (cd "$destination" && sha256sum -c SHA256SUMS >/dev/null)
  printf '%s\n' "$destination"
  exit 0
fi
readonly staging="$(mktemp -d "$snapshot_root/.staging-$expected_commit.XXXXXX")"
cp -a "$source_root/sprites" "$staging/sprites"
cp "$source_root/manifest.json" "$staging/manifest.json"
readonly actual_files="$(find "$staging/sprites" -type f -printf '\0' | wc -c | tr -d ' ')"
[[ "$actual_files" == "$expected_files" ]] || { echo 'Snapshot contains files outside the selected icon package' >&2; exit 1; }
jq -r '.assets[] | "\(.sha256)  sprites/\(.server_path)"' "$source_root/manifest.json" > "$staging/SHA256SUMS"
(cd "$staging" && sha256sum -c SHA256SUMS >/dev/null)
printf '%s\n' "$expected_commit" > "$staging/source-commit.txt"
printf '%s\n' "$actual_files" > "$staging/file-count.txt"
# 全部选择/数量/字节检查通过后才发布；旧快照不覆盖、不自动删除。
mv -T "$staging" "$destination"
printf '%s\n' "$destination"
