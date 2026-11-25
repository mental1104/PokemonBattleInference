-- 在只读事务中对所有业务表和物化视图计算行数及完整有序行摘要。
-- 仅依赖 PostgreSQL 自带函数；摘要不输出原始业务行，空表使用空字符串摘要。
-- 调用方分别在生产源和隔离恢复目标运行本文件并逐字比较结果。
\set ON_ERROR_STOP on
\pset tuples_only on
\pset format unaligned
BEGIN READ ONLY;
SELECT format(
  'SELECT %L, count(*), md5(coalesce(string_agg(row_to_json(t)::text, chr(10) ORDER BY row_to_json(t)::text COLLATE "C"), %L)) FROM %I.%I t;',
  n.nspname || '.' || c.relname, '', n.nspname, c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog','information_schema')
  AND n.nspname NOT LIKE 'pg_toast%%' AND c.relkind IN ('r','m')
ORDER BY n.nspname COLLATE "C", c.relname COLLATE "C"
\gexec
COMMIT;
