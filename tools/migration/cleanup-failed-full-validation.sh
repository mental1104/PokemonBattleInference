#!/bin/sh
# 用途：释放本次20分钟超时、已停止的独占测试PGDATA，避免重跑与恢复副本挤满SSD。
# 输入：无参数；维护定义只挂载固定失败目录和其HDD证据，不接受外部路径。
# 输出：清理前物理大小/顶层文件清单写入HDD，成功打印摘要，任何保护条件不符退出非零。
# 依赖：PostgreSQL16镜像的POSIX工具；副作用仅删除该可由固定源码重建的失败测试数据。
set -eu
umask 077
[ "$#" = 0 ] && [ "$(id -u)" = 0 ] || exit 2
[ "$(cat /validation-data/PG_VERSION)" = 16 ] || exit 2
# postmaster.pid缺失且控制文件明确记录正常停机，才能删除；从不自行停止未知数据库。
[ ! -e /validation-data/postmaster.pid ] || exit 2
grep -F 'context deadline exceeded' /reports/initialization.log >/dev/null
pg_controldata /validation-data > /reports/pg-control-final.txt
grep -E '^Database cluster state: +shut down$' /reports/pg-control-final.txt >/dev/null
grep -Fx 'a3f0ff728cb9473fa6cd8a93f6fa010f3422ac4e' /reports/source-commit.txt >/dev/null
du -sb /validation-data > /reports/disposable-pgdata-size.txt
find /validation-data -mindepth 1 -maxdepth 1 -print > /reports/disposable-pgdata-files.txt
# 挂载根保留，find不跨文件系统；只清理自己失败的物理副本，不触及任何HDD备份或素材。
find /validation-data -xdev -mindepth 1 -delete
printf 'Owned failed validation data removed; source and failure evidence retained.\n'
