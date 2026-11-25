# 先由声明的维护服务构建 pokemon-validation；Python/编译工具只存在于构建阶段。
# 可通过 PBI_BUILD_IMAGE 选择拥有同样 C++/Go/Boost/JSON 工具链的已核验构建镜像。
ARG PBI_BUILD_IMAGE=pokemon-migration-validation:local
FROM ${PBI_BUILD_IMAGE} AS build
WORKDIR /source
COPY core /source/core
COPY contracts/c /source/contracts/c
RUN cmake -S core -B /build/core -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    && cmake --build /build/core --target pbi_abi -j2
COPY server /source/server
WORKDIR /source/server
# -a 避免外部静态库变化被 Go 缓存忽略；db-init 不依赖 CGO。
RUN CGO_ENABLED=1 CGO_LDFLAGS=-L/build/core go build -a -trimpath -ldflags='-s -w' -o /out/pbi-server ./cmd/pbi-server \
    && CGO_ENABLED=1 CGO_LDFLAGS=-L/build/core go build -a -trimpath -ldflags='-s -w' -o /out/pbi-core-worker ./cmd/pbi-core-worker \
    && CGO_ENABLED=1 CGO_LDFLAGS=-L/build/core go build -a -trimpath -ldflags='-s -w' -o /out/pbi-worker ./cmd/pbi-worker \
    && CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /out/pbi-healthcheck ./cmd/pbi-healthcheck \
    && CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /out/pbi-db-init ./cmd/pbi-db-init
# 从实际二进制的 ldd 结果复制精确运行库，保留 ELF loader 原路径，不猜测 glibc/C++ ABI 版本。
RUN mkdir -p /out/rootfs/usr/local/bin /out/rootfs/etc/ssl/certs /out/rootfs/app \
    && cp /out/pbi-server /out/pbi-core-worker /out/pbi-worker /out/pbi-healthcheck /out/pbi-db-init /out/rootfs/usr/local/bin/ \
    && cp /etc/ssl/certs/ca-certificates.crt /out/rootfs/etc/ssl/certs/ \
    && ldd /out/pbi-server /out/pbi-core-worker /out/pbi-worker \
       | awk '/=> \// {print $3} /^[[:space:]]*\// && $1 !~ /:$/ {print $1}' \
       | sort -u \
       | while IFS= read -r runtime_library; do cp -L --parents "$runtime_library" /out/rootfs || exit 1; done

# 运行镜像只有 Go 应用、对应原生运行库、TLS 根证书与来源许可，没有 shell/Python/编译器。
FROM scratch AS runtime
COPY --from=build /out/rootfs/ /
COPY server/internal/knowledge/LICENSE.pokeapi.txt /usr/share/licenses/pbi/PokeAPI.txt
# API和初始化镜像共同保留项目许可及已登记的完整第三方声明，随最终运行产物交付。
COPY LICENSE THIRD_PARTY_LICENSES.md /usr/share/licenses/pbi/
COPY server/internal/knowledge/manifest.json /usr/share/pbi/postgres-knowledge-manifest.json
USER 1026:100
WORKDIR /app

# 初始化镜像单独携带固定 CSV；不挂载或复制任何生产数据库状态。
FROM runtime AS db-init
COPY submodules/pokeapi/data/v2/csv /usr/share/pbi/csv
ENTRYPOINT ["/usr/local/bin/pbi-db-init"]
CMD ["--csv-root", "/usr/share/pbi/csv"]

# 默认产物是 API 镜像，复杂原生请求通过同镜像的单请求 Worker 子进程执行。
FROM runtime AS server
ENV PBI_LISTEN=0.0.0.0:41105
EXPOSE 41105
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD ["/usr/local/bin/pbi-healthcheck"]
ENTRYPOINT ["/usr/local/bin/pbi-server"]
