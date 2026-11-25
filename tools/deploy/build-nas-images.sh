#!/usr/bin/env bash
# 用途：通过NAS唯一nas-shared构建器，使用已导出的OCI工具链构建固定源码的三个发布镜像。
# 输入：PBI_NAS_BUILD_SOURCE为干净checkout；PBI_NAS_TOOLCHAIN_LAYOUT为已核验本地OCI目录。
#       PBI_NAS_{SERVER,DATA,FRONTEND}_IMAGE为明确标签；PBI_NAS_BUILD_REPORT为私有HDD报告目录。
# 输出：构建日志、固定源码SHA和真实image JSON；不访问生产DSN、不启停业务、不清理共享缓存。
# 依赖：nas-manage.sh build、Git、jq、Docker；副作用仅为本项目镜像和共享构建缓存。
set -euo pipefail
umask 077
readonly source_root="${PBI_NAS_BUILD_SOURCE:?Set the clean source checkout}"
readonly toolchain="${PBI_NAS_TOOLCHAIN_LAYOUT:?Set the verified OCI layout directory}"
readonly report="${PBI_NAS_BUILD_REPORT:?Set the private HDD build report directory}"
readonly server_image="${PBI_NAS_SERVER_IMAGE:?Set the server image tag}"
readonly data_image="${PBI_NAS_DATA_IMAGE:?Set the data image tag}"
readonly frontend_image="${PBI_NAS_FRONTEND_IMAGE:?Set the frontend image tag}"
readonly manager=/volume2/code/infra/homelab-services/tools/nas-management/nas-manage.sh
[[ "$source_root" == /* && "$toolchain" == /* && "$report" == /* ]] || exit 2
[[ -z "$(git -C "$source_root" status --porcelain)" ]] || { echo 'Build source must be clean' >&2; exit 2; }
readonly revision="$(git -C "$source_root" rev-parse HEAD)"
readonly toolchain_digest="$(jq -er '.manifests | if length == 1 then .[0].digest else error("expected one toolchain image") end' "$toolchain/index.json")"
[[ "$toolchain_digest" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
mkdir -p "$report"
printf '%s\n' "$revision" > "$report/source-commit.txt"
cp "$toolchain/index.json" "$report/toolchain-index.json"
# OCI命名上下文使共享BuildKit直接读取固定工具链；不依赖另一个Docker builder的本地标签缓存。
for target in server db-init; do
  image="$server_image"
  [[ "$target" != db-init ]] || image="$data_image"
  bash "$manager" build build --file "$source_root/deploy/Dockerfile.go" --target "$target" \
    --build-arg PBI_BUILD_IMAGE=pbi_toolchain --build-arg "PBI_SOURCE_REVISION=$revision" \
    --build-context "pbi_toolchain=oci-layout://$toolchain@$toolchain_digest" \
    --tag "$image" --load "$source_root" > "$report/build-$target.log" 2>&1
done
bash "$manager" build build --file "$source_root/web/Dockerfile" \
  --label "org.opencontainers.image.revision=$revision" --tag "$frontend_image" --load "$source_root" \
  > "$report/build-frontend.log" 2>&1
docker image inspect "$server_image" "$data_image" "$frontend_image" --format '{{json .}}' > "$report/images.jsonl"
printf 'NAS images built from committed source %s.\n' "$revision"
